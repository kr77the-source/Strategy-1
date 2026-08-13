from datetime import datetime
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
import pandas as pd
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Live Auto-Scanning Engine & Performance Tracker",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Auto-refresh every 10 seconds for live scanning
st_autorefresh(interval=10000, key="datarefresh")

# -----------------------------------------------------------------------------
# CSS FOR UI CARDS (EXACT SCREENSHOT LOOK)
# -----------------------------------------------------------------------------
st.markdown("""
    <style>
    .status-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 8px;
        padding: 14px 18px;
        color: #ffffff;
        font-size: 16px;
        font-weight: 500;
        margin-bottom: 12px;
    }
    .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 8px;
        padding: 14px 18px;
        color: #ffffff;
        font-size: 16px;
        font-weight: 500;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# APP HEADER
# -----------------------------------------------------------------------------
st.markdown("### 🎯 Live Auto-Scanning Engine & Performance Tracker")

# Current IST Time
now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
current_date = now_ist.strftime("%Y-%m-%d")
current_time = now_ist.strftime("%H:%M:%S")

# -----------------------------------------------------------------------------
# WATCHLIST & SCANNING LOGIC (REAL DATA VIA YFINANCE)
# -----------------------------------------------------------------------------
# Aap apni watchlist yahan add kar sakte hain
WATCHLIST = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]

def scan_live_signals():
    signals = []
    
    for symbol in WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            # Fetching 1-day interval data for real levels
            df = ticker.history(period="5d", interval="15m")
            
            if not df.empty and len(df) >= 2:
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                
                close_price = round(float(latest['Close']), 1)
                high_price = round(float(prev['High']), 1)
                low_price = round(float(prev['Low']), 1)
                
                # Dynamic Strategy: Entry at CMP, SL at Prev Low, Target based on Risk-Reward
                entry_trigger = close_price
                risk = abs(entry_trigger - low_price)
                
                # If risk is minimal, set 0.5% default buffer
                if risk == 0:
                    risk = round(entry_trigger * 0.005, 1)
                    
                stop_loss = round(entry_trigger - risk, 1)
                target = round(entry_trigger + (risk * 1.5), 1)
                
                # Calculating live P&L status
                pnl_pts = round(close_price - entry_trigger, 1)
                status = "TARGET" if close_price >= target else ("SL" if close_price <= stop_loss else "LIVE")

                signals.append({
                    "Symbol": symbol.replace(".NS", ""),
                    "Entry Trigger": entry_trigger,
                    "Stop Loss (SL)": stop_loss,
                    "Target (Exit)": target,
                    "Current Price": close_price,
                    "Status": status,
                    "P&L Pts": pnl_pts
                })
        except Exception:
            continue
            
    return pd.DataFrame(signals)

# Fetch Scan Results
df_signals = scan_live_signals()

# -----------------------------------------------------------------------------
# CALCULATE SUMMARY METRICS
# -----------------------------------------------------------------------------
if not df_signals.empty:
    total_trades = len(df_signals)
    targets_hit = len(df_signals[df_signals["Status"] == "TARGET"])
    sl_hit = len(df_signals[df_signals["Status"] == "SL"])
    overall_pnl = round(df_signals["P&L Pts"].sum(), 2)
else:
    total_trades = 0
    targets_hit = 0
    sl_hit = 0
    overall_pnl = 0.0

# P&L Color styling
pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"

# -----------------------------------------------------------------------------
# DISPLAY STATUS CARDS
# -----------------------------------------------------------------------------
st.markdown(f"""
    <div class="status-card">
        <b>Live Engine Status:</b> 🟢 AUTO SCANNING LIVE | <b>Date:</b> {current_date} | <b>Last Updated (IST):</b> {current_time}
    </div>
""", unsafe_allow_html=True)

st.markdown(f"""
    <div class="pnl-card">
        📊 <b>Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>Overall P&L:</b> <span style="color:{pnl_color};">{overall_pnl} Pts</span>
    </div>
""", unsafe_allow_html=True)

st.markdown("---")

# -----------------------------------------------------------------------------
# DISPLAY SIGNALS TABLE
# -----------------------------------------------------------------------------
st.markdown("### 📋 Subah Se Mile Saare Signals & Live Status")

if not df_signals.empty:
    display_df = df_signals[["Entry Trigger", "Stop Loss (SL)", "Target (Exit)"]]
    st.dataframe(display_df, width="stretch")
else:
    st.info("Scanning for live signals...")
