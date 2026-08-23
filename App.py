import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# PAGE CONFIG & STYLES
# =============================================================================
st.set_page_config(page_title="Multi-Asset Algo Terminal", layout="wide")

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

RUPEE = "₹"
DEFAULT_STOCKS = ["YESBANK.NS", "PCJEWELLER.NS", "RELIANCE.NS", "TCS.NS", "SBIN.NS"]
SETTINGS_FILE = "strategy_settings.json"

# =============================================================================
# SETTINGS ENGINE
# =============================================================================
def load_settings():
    defaults = {
        "fast_ma_len": 20, "slow_ma_len": 50, "trade_value": 3000, "leverage": 5,
        "watchlist": DEFAULT_STOCKS.copy(),
        "NIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "BANKNIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "FINNIFTY_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "NIFTY_mult": 1, "BANKNIFTY_mult": 1, "FINNIFTY_mult": 1
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                defaults.update(json.load(f))
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
# REAL SPOT ATR BREAKOUT BACKTEST ENGINE (BUG FIXED)
# =============================================================================
def run_real_indicator_backtest(index_symbol, qty_multiplier=1, allowed_days=None):
    if allowed_days is None:
        allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    ticker_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
    ticker = ticker_map.get(index_symbol, "^NSEI")
    
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
    except Exception as e:
        st.error(f"Data Fetch Error: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        st.warning("Yahoo Finance se koi data nahi mila.")
        return pd.DataFrame()

    # FIX MULTIINDEX COLUMNS ISSUE IN YFINANCE
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Calculate True Range & ATR
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift(1))
    low_close = np.abs(df['Low'] - df['Close'].shift(1))
    df['TR'] = np.maximum(high_low, np.maximum(high_close, low_close))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df.dropna(inplace=True)

    trades = []
    lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
    total_qty = lot_sizes.get(index_symbol, 15) * int(qty_multiplier)

    for idx, row in df.iterrows():
        day_name = idx.strftime("%A")
        if day_name not in allowed_days:
            continue

        trade_date = idx.strftime("%Y-%m-%d")
        open_p = float(row["Open"])
        high_p = float(row["High"])
        low_p = float(row["Low"])
        close_p = float(row["Close"])
        atr_val = float(row["ATR"])

        breakout_threshold = 0.4 * atr_val

        if (high_p - open_p) >= breakout_threshold and close_p > open_p:
            leg = "CE"
            entry_spot = open_p + breakout_threshold
            sl_spot = entry_spot - (0.4 * atr_val)
            target_spot = entry_spot + (0.8 * atr_val)
        elif (open_p - low_p) >= breakout_threshold and close_p < open_p:
            leg = "PE"
            entry_spot = open_p - breakout_threshold
            sl_spot = entry_spot + (0.4 * atr_val)
            target_spot = entry_spot - (0.8 * atr_val)
        else:
            continue

        if leg == "CE":
            if high_p >= target_spot:
                exit_spot = target_spot
                status = "TARGET_PROFIT"
            elif low_p <= sl_spot:
                exit_spot = sl_spot
                status = "SL_HIT"
            else:
                exit_spot = close_p
                status = "EOD_EXIT"
            points_gained = exit_spot - entry_spot
        else:
            if low_p <= target_spot:
                exit_spot = target_spot
                status = "TARGET_PROFIT"
            elif high_p >= sl_spot:
                exit_spot = sl_spot
                status = "SL_HIT"
            else:
                exit_spot = close_p
                status = "EOD_EXIT"
            points_gained = entry_spot - exit_spot

        gross_pnl = points_gained * total_qty
        turnover = (entry_spot + exit_spot) * total_qty
        charges = round(min(40.0, turnover * 0.0002) + 15.0, 2)
        net_pnl = gross_pnl - charges

        trades.append({
            "Date": trade_date, "Day": day_name, "Index": index_symbol, "Leg": leg,
            "Entry Spot": round(entry_spot, 2), "Exit Spot": round(exit_spot, 2),
            "Points": round(points_gained, 2), "Gross PnL": round(gross_pnl, 2),
            "Taxes": charges, "Net PnL": round(net_pnl, 2), "Status": status
        })

    return pd.DataFrame(trades)

# =============================================================================
# UI & TAB CONFIG
# =============================================================================
SAVED_CFG = load_settings()

if "watchlist" not in st.session_state:
    st.session_state.watchlist = SAVED_CFG.get("watchlist", DEFAULT_STOCKS.copy())

with st.sidebar:
    st.header("⚙️ Strategy Settings")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=int(SAVED_CFG.get("fast_ma_len", 20)))
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=int(SAVED_CFG.get("slow_ma_len", 50)))
    
    if st.button("💾 SAVE SIDEBAR SETTINGS", type="primary"):
        current_cfg = {"fast_ma_len": FAST_MA_LEN, "slow_ma_len": SLOW_MA_LEN}
        if save_settings_to_file(current_cfg):
            st.success("✅ Saved!")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Normal Stock (EMA)", "Reverse Stock (EMA)", "⚡ NIFTY Algo", "⚡ BANKNIFTY Algo", "⚡ FINNIFTY Algo"
])

with tab1:
    st.markdown("### 🟢 Live Normal Stock Strategy")

with tab2:
    st.markdown("### 🔴 Live Reverse Stock Strategy")

def render_index_tab(index_name):
    st.markdown(f"### 🎯 Real ATR Breakout Terminal — {index_name}")
    
    saved_days = SAVED_CFG.get(f"{index_name}_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    saved_mult = int(SAVED_CFG.get(f"{index_name}_mult", 1))

    col_days, col_mult, col_save = st.columns([3, 1, 1])
    with col_days:
        days_selected = st.multiselect(
            f"Execution Days for {index_name}:",
            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            default=saved_days, key=f"days_{index_name}"
        )
    with col_mult:
        qty_mult = st.selectbox("Lot Multiplier:", [1, 2, 3, 5, 10], index=0, key=f"mult_{index_name}")

    with col_save:
        st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button(f"💾 Save {index_name} Settings", key=f"save_btn_{index_name}"):
            if save_settings_to_file({f"{index_name}_days": days_selected, f"{index_name}_mult": qty_mult}):
                st.success("✅ Saved!")

    st.markdown("---")

    if st.button(f"▶️ Run Real Backtest ({index_name})", key=f"btn_{index_name}", type="primary"):
        with st.spinner(f"Fetching real market data for {index_name}..."):
            df_res = run_real_indicator_backtest(index_name, qty_multiplier=qty_mult, allowed_days=days_selected)
            st.session_state[f"res_{index_name}"] = df_res

    df_res = st.session_state.get(f"res_{index_name}")
    if df_res is not None and not df_res.empty:
        tot_net = df_res["Net PnL"].sum()
        tot_tax = df_res["Taxes"].sum()
        net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"
        
        st.markdown(f"""
            <div class="top-pnl-card">
                <div class="pnl-grid">
                    <div><span style="font-size: 11px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 16px; font-weight: bold;">{len(df_res)}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">TOTAL POINTS</span><br><span style="font-size: 16px; font-weight: bold;">{df_res['Points'].sum():.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">TAXES & CHARGES</span><br><span style="font-size: 16px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_tax:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">NET P&L</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 📊 Day-Wise Breakdown")
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
