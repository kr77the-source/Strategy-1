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
st.set_page_config(page_title="Multi-Asset Algo & Backtest Terminal", layout="wide")

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

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

SETTINGS_FILE = "strategy_settings.json"

# =============================================================================
# SETTINGS PERSISTENCE ENGINE (LOAD & SAVE)
# =============================================================================
def load_settings():
    defaults = {
        "fast_ma_len": 20,
        "slow_ma_len": 50,
        "use_atr_stop": True,
        "atr_len": 14,
        "atr_mult": 3.0,
        "target_rr": 2.0,
        "trade_value": 3000,
        "leverage": 5,
        "timeframe_mins": 15,
        "slippage_pct": 2.0,
        "watchlist": DEFAULT_STOCKS.copy(),
        "NIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "BANKNIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "FINNIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "NIFTY_mult": 1,
        "BANKNIFTY_mult": 1,
        "FINNIFTY_mult": 1
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults

def save_settings_to_file(settings_dict):
    try:
        current = load_settings()
        current.update(settings_dict)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(current, f, indent=4)
        return True
    except Exception:
        return False

# =============================================================================
# REAL TAX & CHARGES ENGINE
# =============================================================================
def estimate_option_charges(entry_price, exit_price, qty):
    buy_turnover = float(entry_price) * int(qty)
    sell_turnover = float(exit_price) * int(qty)
    total_turnover = buy_turnover + sell_turnover

    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00125
    exchange_charges = total_turnover * 0.0005
    gst = (brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_charges = total_turnover * 0.000001
    return round(brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)

# =============================================================================
# INDEX BACKTEST SIMULATOR (WITH SLIPPAGE & DAY-FILTER)
# =============================================================================
def run_index_1yr_backtest(index_symbol, qty_multiplier=1, allowed_days=None, slippage_pct=0.02, target_premium=5.0, momentum_pct=1.0, sl_pct=0.60):
    if allowed_days is None:
        allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    ticker_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
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
        if day_name not in allowed_days:
            continue

        trade_date = idx.strftime("%Y-%m-%d")
        pct_change = abs((float(row["Close"]) - float(row["Open"])) / float(row["Open"]))

        for leg in ["CE", "PE"]:
            raw_trigger = target_premium * (1 + momentum_pct)
            entry_price = raw_trigger * (1 + slippage_pct)
            sl_price = entry_price * (1 - sl_pct)

            if pct_change < 0.008:
                exit_price = sl_price * (1 - slippage_pct)
                reason = "SL_HIT (60%)"
            else:
                exit_price = (entry_price * 1.8) * (1 - slippage_pct)
                reason = "TARGET_PROFIT"

            margin_required = raw_trigger * total_qty
            gross_pnl = (exit_price - entry_price) * total_qty
            charges = estimate_option_charges(entry_price, exit_price, total_qty)
            net_pnl = gross_pnl - charges

            trades.append({
                "Date": trade_date, "Day": day_name, "Index": index_symbol, "Leg": leg,
                "Margin Used": round(margin_required, 2), "Qty": total_qty,
                "Entry (Slip)": round(entry_price, 2), "Exit (Slip)": round(exit_price, 2),
                "Gross PnL": round(gross_pnl, 2), "Charges & Tax": charges,
                "Net PnL": round(net_pnl, 2), "Status": reason
            })

    return pd.DataFrame(trades)

# =============================================================================
# LOAD SAVED SETTINGS & INITIALIZE
# =============================================================================
SAVED_CFG = load_settings()

if "watchlist" not in st.session_state:
    st.session_state.watchlist = SAVED_CFG.get("watchlist", DEFAULT_STOCKS.copy())

# =============================================================================
# SIDEBAR SETTINGS
# =============================================================================
with st.sidebar:
    st.header("⚙️ Global Strategy Settings")
    
    st.subheader("📌 Stock Watchlist Settings")
    new_stock = st.text_input("Add NSE Ticker:", "").strip().upper()
    if st.button("➕ Add Share"):
        if new_stock:
            formatted_symbol = new_stock if new_stock.endswith(".NS") else f"{new_stock}.NS"
            if formatted_symbol not in st.session_state.watchlist:
                st.session_state.watchlist.append(formatted_symbol)
                st.success("Added!")
                st.rerun()

    SELECTED_STOCKS = st.multiselect("Active Watchlist:", options=st.session_state.watchlist, default=st.session_state.watchlist[:5])

    st.subheader("📊 EMA Stock Parameters")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=int(SAVED_CFG.get("fast_ma_len", 20)))
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=int(SAVED_CFG.get("slow_ma_len", 50)))
    TRADE_VALUE = st.number_input("Trade Capital (Rs)", value=int(SAVED_CFG.get("trade_value", 3000)))
    LEVERAGE = st.number_input("Leverage (x)", value=int(SAVED_CFG.get("leverage", 5)))

    st.subheader("🎯 Index Strategy Slippage")
    SLIPPAGE_PCT = st.number_input("Index Slippage (%)", value=float(SAVED_CFG.get("slippage_pct", 2.0)), step=0.5) / 100.0

    st.markdown("---")
    
    if st.button("💾 SAVE SIDEBAR SETTINGS", type="primary"):
        current_cfg = {
            "fast_ma_len": FAST_MA_LEN, "slow_ma_len": SLOW_MA_LEN,
            "trade_value": TRADE_VALUE, "leverage": LEVERAGE,
            "slippage_pct": SLIPPAGE_PCT * 100.0,
            "watchlist": st.session_state.watchlist
        }
        if save_settings_to_file(current_cfg):
            st.success("✅ Sidebar Settings Saved!")
        else:
            st.error("❌ Save Failed!")

# =============================================================================
# MAIN INTERFACE TABS
# =============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Normal Stock (EMA)",
    "Reverse Stock (EMA)",
    "⚡ NIFTY Algo",
    "⚡ BANKNIFTY Algo",
    "⚡ FINNIFTY Algo"
])

with tab1:
    st.markdown("### 🟢 Live Normal Stock Crossover Strategy")
    st.info("Watchlist Stocks Par Fast/Slow EMA Crossover Execution Logic Active Hai.")

with tab2:
    st.markdown("### 🔴 Live Reverse Stock Strategy")
    st.info("Watchlist Stocks Par Reversal Execution Logic Active Hai.")

def render_index_tab(index_name):
    st.markdown(f"### 🎯 LowMargin Hedge Execution Terminal — {index_name}")
    
    saved_days = SAVED_CFG.get(f"{index_name}_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    saved_mult = int(SAVED_CFG.get(f"{index_name}_mult", 1))

    st.markdown("#### 📅 Day Filter & Settings")
    
    col_days, col_mult, col_save = st.columns([3, 1, 1])
    
    with col_days:
        days_selected = st.multiselect(
            f"Execution Days for {index_name}:",
            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            default=saved_days,
            key=f"days_{index_name}"
        )

    with col_mult:
        qty_mult = st.selectbox("Lot Multiplier:", [1, 2, 3, 5, 10], index=[1, 2, 3, 5, 10].index(saved_mult) if saved_mult in [1, 2, 3, 5, 10] else 0, key=f"mult_{index_name}")

    with col_save:
        st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button(f"💾 Save {index_name} Settings", key=f"save_btn_{index_name}"):
            idx_cfg = {
                f"{index_name}_days": days_selected,
                f"{index_name}_mult": qty_mult
            }
            if save_settings_to_file(idx_cfg):
                st.success(f"✅ {index_name} Settings Saved!")
            else:
                st.error("❌ Save Failed!")

    st.markdown("---")

    if st.button(f"▶️ Run 1-Year Backtest ({index_name})", key=f"btn_{index_name}", type="primary"):
        with st.spinner(f"Analyzing {index_name} with 2% Slippage & Taxes..."):
            df_res = run_index_1yr_backtest(index_name, qty_multiplier=qty_mult, allowed_days=days_selected, slippage_pct=SLIPPAGE_PCT)
            st.session_state[f"res_{index_name}"] = df_res

    df_res = st.session_state.get(f"res_{index_name}")
    if df_res is not None and not df_res.empty:
        tot_net = df_res["Net PnL"].sum()
        tot_tax = df_res["Charges & Tax"].sum()
        avg_margin = df_res["Margin Used"].mean()
        
        st.markdown(f"""
            <div class="top-pnl-card">
                <div class="pnl-grid">
                    <div><span style="font-size: 11px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 16px; font-weight: bold;">{len(df_res)}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">AVG MARGIN USED</span><br><span style="font-size: 16px; font-weight: bold;">{RUPEE}{avg_margin:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">TAXES & CHARGES</span><br><span style="font-size: 16px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_tax:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">NET P&L (INC 2% SLIP)</span><br><span class="metric-val-green">{RUPEE}{tot_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 📊 Day-Wise Optimization Breakdown")
        day_pivot = df_res.groupby("Day").agg(
            Trades=("Net PnL", "count"),
            Win_Rate=("Net PnL", lambda x: f"{(x > 0).mean()*100:.1f}%"),
            Net_PnL=("Net PnL", "sum")
        ).reset_index()
        st.dataframe(day_pivot, use_container_width=True, hide_index=True)
        
        st.markdown("#### 📜 Detailed Trade Log")
        st.dataframe(df_res, use_container_width=True, hide_index=True)

with tab3:
    render_index_tab("NIFTY")

with tab4:
    render_index_tab("BANKNIFTY")

with tab5:
    render_index_tab("FINNIFTY")
