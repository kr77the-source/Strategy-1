from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="20 EMA + VWAP Pullback Live Dashboard", layout="wide"
)

# Auto refresh every 10 seconds
st_autorefresh(interval=10000, key="datarefresh")

# -----------------------------------------------------------------------------
# CUSTOM CSS: REMOVE GAPS & REDUCE FONT SIZES
# -----------------------------------------------------------------------------
st.markdown("""
    <style>
    /* Top & Side Gap Reduction */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    
    /* Remove Header Empty Space */
    header[data-testid="stHeader"] {
        background: transparent;
        height: 1.5rem;
    }
    
    /* Compact Headings */
    h3 {
        font-size: 1.1rem !important;
        margin-top: -0.5rem !important;
        margin-bottom: 0.4rem !important;
        padding: 0px !important;
    }
    
    /* Compact Card Styling */
    .status-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 6px 10px;
        color: #ffffff;
        font-size: 12px;
        margin-bottom: 5px;
    }
    
    .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 6px 10px;
        color: #ffffff;
        font-size: 12px;
        margin-bottom: 8px;
    }
    
    /* Reduce Horizontal Rule Gap */
    hr {
        margin-top: 0.3rem !important;
        margin-bottom: 0.3rem !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("### 🎯 20 EMA + VWAP Pullback Dashboard")

now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
current_date = now_ist.strftime("%Y-%m-%d")
current_time = now_ist.strftime("%H:%M:%S")

# 4 Stocks Selected for Trading (Budget ₹12,500 each = ₹50,000 total)
WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS"
]

TOTAL_CAPITAL = 50000.0
CAPITAL_PER_STOCK = 12500.0  # ₹50,000 / 4 stocks

# -----------------------------------------------------------------------------
# TECHNICAL INDICATOR HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def calculate_vwap(df):
    """Calculates Intraday VWAP"""
    v = df['Volume'].values
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * v).cumsum() / v.cumsum()

def calculate_atr(df, period=14):
    """Calculates Average True Range (ATR 14)"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

# -----------------------------------------------------------------------------
# 20 EMA + VWAP PULLBACK SCANNING ENGINE
# -----------------------------------------------------------------------------
def scan_and_lock_trades():
    all_signals = []

    for symbol in WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 25:
                continue

            # Indicators Calculation
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)
            df['ATR14'] = calculate_atr(df, 14)

            opens = df["Open"].values
            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            ema20 = df["EMA20"].values
            vwap = df["VWAP"].values
            atr14 = df["ATR14"].values
            timestamps = df.index

            trade_active = False  # Ensure single active trade per stock

            for i in range(20, len(df)):
                if trade_active:
                    continue

                curr_close = closes[i]
                curr_open = opens[i]
                curr_high = highs[i]
                curr_low = lows[i]
                curr_ema = ema20[i]
                curr_vwap = vwap[i]
                curr_atr = atr14[i]

                if np.isnan(curr_atr) or curr_atr == 0:
                    continue

                signal_time = timestamps[i].strftime("%H:%M")

                # 🟢 LONG TRIGGER: 20 EMA > VWAP & Pullback to 20 EMA
                bullish_trend = curr_ema > curr_vwap
                long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                # 🔴 SHORT TRIGGER: 20 EMA < VWAP & Pullback to 20 EMA
                bearish_trend = curr_ema < curr_vwap
                short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if long_pullback:
                    entry = round(float(curr_close), 2)
                    sl = round(float(entry - (1.5 * curr_atr)), 2)
                    risk = entry - sl
                    target = round(float(entry + (2.0 * risk)), 2)
                    
                    qty = max(1, int(CAPITAL_PER_STOCK / entry))

                    final_status = "LIVE 🟡"
                    cmp_price = round(float(closes[-1]), 2)
                    final_pnl = round((cmp_price - entry) * qty, 2)

                    # Check future candles for SL/TP exit
                    for j in range(i + 1, len(df)):
                        if lows[j] <= sl:
                            final_status = "SL HIT 🔴"
                            final_pnl = round((sl - entry) * qty, 2)
                            break
                        elif highs[j] >= target:
                            final_status = "TARGET 🟢"
                            final_pnl = round((target - entry) * qty, 2)
                            break

                    all_signals.append({
                        "Time": signal_time,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": "BUY 🟢",
                        "Qty": qty,
                        "Entry Price": entry,
                        "Stop Loss (SL)": sl,
                        "Target": target,
                        "CMP": cmp_price,
                        "Status": final_status,
                        "P&L (₹)": final_pnl
                    })
                    trade_active = True

                elif short_pullback:
                    entry = round(float(curr_close), 2)
                    sl = round(float(entry + (1.5 * curr_atr)), 2)
                    risk = sl - entry
                    target = round(float(entry - (2.0 * risk)), 2)
                    
                    qty = max(1, int(CAPITAL_PER_STOCK / entry))

                    final_status = "LIVE 🟡"
                    cmp_price = round(float(closes[-1]), 2)
                    final_pnl = round((entry - cmp_price) * qty, 2)

                    # Check future candles for SL/TP exit
                    for j in range(i + 1, len(df)):
                        if highs[j] >= sl:
                            final_status = "SL HIT 🔴"
                            final_pnl = round((entry - sl) * qty, 2)
                            break
                        elif lows[j] <= target:
                            final_status = "TARGET 🟢"
                            final_pnl = round((entry - target) * qty, 2)
                            break

                    all_signals.append({
                        "Time": signal_time,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": "SELL 🔴",
                        "Qty": qty,
                        "Entry Price": entry,
                        "Stop Loss (SL)": sl,
                        "Target": target,
                        "CMP": cmp_price,
                        "Status": final_status,
                        "P&L (₹)": final_pnl
                    })
                    trade_active = True

        except Exception:
            continue

    return pd.DataFrame(all_signals)

# -----------------------------------------------------------------------------
# DISPLAY METRICS & STREAMLIT DASHBOARD
# -----------------------------------------------------------------------------
df_signals = scan_and_lock_trades()

if not df_signals.empty:
    total_trades = len(df_signals)
    targets_hit = len(df_signals[df_signals["Status"].str.contains("TARGET")])
    sl_hit = len(df_signals[df_signals["Status"].str.contains("SL HIT")])
    overall_pnl = round(df_signals["P&L (₹)"].sum(), 2)
else:
    total_trades = 0
    targets_hit = 0
    sl_hit = 0
    overall_pnl = 0.0

pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"

# Top Engine Status Header
st.markdown(f"""
    <div class="status-card">
        <b>Status:</b> 🟢 SCANNING | <b>Date:</b> {current_date} | <b>Time:</b> {current_time}
    </div>
""", unsafe_allow_html=True)

# Performance P&L Summary Card
st.markdown(f"""
    <div class="pnl-card">
        📊 <b>Cap:</b> ₹50k | <b>Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">₹{overall_pnl}</span>
    </div>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("### 📋 Trades Log")

if not df_signals.empty:
    st.dataframe(
        df_signals[
            [
                "Time",
                "Symbol",
                "Type",
                "Qty",
                "Entry Price",
                "Stop Loss (SL)",
                "Target",
                "CMP",
                "Status",
                "P&L (₹)"
            ]
        ],
        use_container_width=True,
    )
else:
    st.info("Abhi tak koi valid trade setup nahi mila hai.")
