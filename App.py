import json
import os
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# PAGE CONFIG & STYLES
# =============================================================================
st.set_page_config(page_title="LowMargin Hedge Algo Terminal", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
header[data-testid="stHeader"] { background: transparent; }
.top-pnl-card {
    background: linear-gradient(135deg, #1e2530 0%, #161b22 100%);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
    color: #ffffff;
}
.pnl-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    text-align: center;
}
@media (min-width: 600px) {
    .pnl-grid {
        grid-template-columns: repeat(5, 1fr);
    }
}
.metric-val-green { color: #4CAF50; font-weight: bold; font-size: 16px; }
.metric-val-red { color: #FF5252; font-weight: bold; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

IST = ZoneInfo("Asia/Kolkata")
RUPEE = "₹"

# =============================================================================
# REAL OPTION CHARGES & TAX CALCULATOR
# =============================================================================
def estimate_option_charges(entry_price, exit_price, qty):
    buy_turnover = float(entry_price) * int(qty)
    sell_turnover = float(exit_price) * int(qty)
    total_turnover = buy_turnover + sell_turnover

    # Standard Zerodha / AngelOne Option Charges Scheme
    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00125  # STT on Options Premium Sell
    exchange_charges = total_turnover * 0.0005  # NSE Option Transaction Fee
    gst = (brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003  # Stamp duty on Buy side
    sebi_charges = total_turnover * 0.000001
    
    total_tax = brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges
    return round(total_tax, 2)

# =============================================================================
# INDEX BACKTEST ENGINE WITH 2% SLIPPAGE & DAY-FILTER
# =============================================================================
def run_index_1yr_backtest(index_symbol, qty_multiplier=1, allowed_days=None, slippage_pct=0.02, target_premium=5.0, momentum_pct=1.0, sl_pct=0.60):
    if allowed_days is None:
        allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    ticker_map = {
        "NIFTY": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "FINNIFTY": "NIFTY_FIN_SERVICE.NS"
    }
    ticker = ticker_map.get(index_symbol, "^NSEI")
    
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    trades = []
    lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
    base_lot = lot_sizes.get(index_symbol, 25)
    total_qty = base_lot * int(qty_multiplier)

    for idx, row in df.iterrows():
        day_name = idx.strftime("%A")
        
        # Day Filter Implementation (Drawdown Optimization)
        if day_name not in allowed_days:
            continue

        trade_date = idx.strftime("%Y-%m-%d")
        daily_close = float(row["Close"])
        daily_open = float(row["Open"])
        pct_change = abs((daily_close - daily_open) / daily_open)

        ce_triggered = pct_change > 0.005
        pe_triggered = pct_change > 0.005

        for leg, triggered in [("CE", ce_triggered), ("PE", pe_triggered)]:
            if triggered:
                raw_trigger = target_premium * (1 + momentum_pct)  # Trigger Price e.g. ₹10
                
                # Applying 2% Slippage on Entry (Buy Price becomes higher)
                entry_price = raw_trigger * (1 + slippage_pct)
                
                # Stoploss 60%
                sl_price = entry_price * (1 - sl_pct)
                
                if pct_change < 0.008:
                    # Applying 2% Slippage on Exit SL (Sell Price becomes lower)
                    exit_price = sl_price * (1 - slippage_pct)
                    reason = "SL_HIT (60%)"
                else:
                    raw_exit = entry_price * 1.8
                    exit_price = raw_exit * (1 - slippage_pct)
                    reason = "TARGET_PROFIT"

                margin_required = raw_trigger * total_qty
                gross_pnl = (exit_price - entry_price) * total_qty
                charges = estimate_option_charges(entry_price, exit_price, total_qty)
                net_pnl = gross_pnl - charges

                trades.append({
                    "Date": trade_date,
                    "Day": day_name,
                    "Index": index_symbol,
                    "Leg": leg,
                    "Margin Used": round(margin_required, 2),
                    "Qty": total_qty,
                    "Entry (Inc 2% Slip)": round(entry_price, 2),
                    "Exit (Inc 2% Slip)": round(exit_price, 2),
                    "Gross PnL": round(gross_pnl, 2),
                    "Charges & Tax": charges,
                    "Net PnL": round(net_pnl, 2),
                    "Status": reason
                })

    return pd.DataFrame(trades)

# =============================================================================
# HELPER FOR MAXIMUM DRAWDOWN CALCULATION
# =============================================================================
def calculate_max_drawdown(net_pnl_series):
    if net_pnl_series.empty:
        return 0.0
    cum_pnl = net_pnl_series.cumsum()
    peak = cum_pnl.cummax()
    drawdown = cum_pnl - peak
    return round(drawdown.min(), 2)

# =============================================================================
# UI TAB RENDERER
# =============================================================================
def render_index_ui(index_name):
    st.markdown(f"### 🎯 LowMargin Hedge Execution Terminal — {index_name}")
    
    # ------------------ Execution Days Multi-Select UI ------------------
    st.markdown("#### 📅 Select Execution Days (Filter Days to Reduce Drawdown)")
    
    col_days, col_mult, col_slip = st.columns([3, 1, 1])
    
    with col_days:
        days_selected = st.multiselect(
            f"Allowed Days for {index_name}:",
            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            default=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            key=f"days_{index_name}"
        )

    with col_mult:
        qty_mult = st.selectbox(f"Qty Multiplier:", [1, 2, 3, 5, 10], index=0, key=f"mult_{index_name}")
        
    with col_slip:
        slippage = st.number_input(f"Slippage (%)", value=2.0, step=0.5, key=f"slip_{index_name}") / 100.0

    st.markdown("---")

    if st.button(f"▶️ Run 1-Year Day-Wise Backtest ({index_name})", key=f"run_btn_{index_name}", type="primary"):
        with st.spinner(f"Analyzing {index_name} with 2% Slippage & Taxes..."):
            df_res = run_index_1yr_backtest(index_name, qty_multiplier=qty_mult, allowed_days=days_selected, slippage_pct=slippage)
            st.session_state[f"res_{index_name}"] = df_res

    df_res = st.session_state.get(f"res_{index_name}")

    if df_res is not None and not df_res.empty:
        tot_trades = len(df_res)
        tot_gross = df_res["Gross PnL"].sum()
        tot_tax = df_res["Charges & Tax"].sum()
        tot_net = df_res["Net PnL"].sum()
        max_dd = calculate_max_drawdown(df_res["Net PnL"])
        avg_margin = df_res["Margin Used"].mean()

        net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"

        st.markdown(f"""
            <div class="top-pnl-card">
                <div class="pnl-grid">
                    <div><span style="font-size: 11px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 16px; font-weight: bold;">{tot_trades}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">AVG MARGIN USED</span><br><span style="font-size: 16px; font-weight: bold;">{RUPEE}{avg_margin:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">CHARGES & TAXES</span><br><span style="font-size: 16px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_tax:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">NET P&L (INC 2% SLIP)</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">MAX DRAWDOWN</span><br><span class="metric-val-red">{RUPEE}{max_dd:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        # ------------ DAY WISE BREAKDOWN ANALYSIS TABLE ------------
        st.markdown("#### 📊 Day-Wise Optimization Breakdown (Find Best Days)")
        
        day_pivot = df_res.groupby("Day").agg(
            Trades=("Net PnL", "count"),
            Win_Rate=("Net PnL", lambda x: f"{(x > 0).mean()*100:.1f}%"),
            Gross_Profit=("Gross PnL", "sum"),
            Taxes=("Charges & Tax", "sum"),
            Net_PnL=("Net PnL", "sum")
        ).reset_index()

        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        day_pivot['Day'] = pd.Categorical(day_pivot['Day'], categories=days_order, ordered=True)
        day_pivot = day_pivot.sort_values('Day')

        st.dataframe(day_pivot, use_container_width=True, hide_index=True)

        st.markdown("#### 📜 Detailed Backtest Trade Log")
        st.dataframe(df_res, use_container_width=True, hide_index=True)
    else:
        st.info("⬆️ Run Button par click karein backtest analysis shuru karne ke liye.")

# =============================================================================
# MAIN APP TABS
# =============================================================================
tab_nifty, tab_bnifty, tab_finnifty = st.tabs([
    "⚡ NIFTY Strategy",
    "⚡ BANKNIFTY Strategy",
    "⚡ FINNIFTY Strategy"
])

with tab_nifty:
    render_index_ui("NIFTY")

with tab_bnifty:
    render_index_ui("BANKNIFTY")

with tab_finnifty:
    render_index_ui("FINNIFTY")
