from datetime import datetime, time
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="REAL LIVE Intraday Scanner (Under ₹300)", layout="wide"
)

# -----------------------------------------------------------------------------
# CUSTOM CSS
# -----------------------------------------------------------------------------
st.markdown("""
    <style>
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }
    h3 {
        font-size: 1.1rem !important;
        margin-top: 0rem !important;
        margin-bottom: 0.5rem !important;
        padding: 0px !important;
    }
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
    hr {
        margin-top: 0.3rem !important;
        margin-bottom: 0.3rem !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("### 🔴 REAL-TIME LIVE INTRADAY DASHBOARD (50 Stocks Under ₹300)")

# -----------------------------------------------------------------------------
# WATCHLIST: 50 High-Volume Stocks Under ₹300 (12 Sectors)
# -----------------------------------------------------------------------------
UNDER_300_WATCHLIST = [
    # Banking & Financials
    "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "UNIONBANK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS",
    # Power & Energy
    "POWERGRID.NS", "NHPC.NS", "SJVN.NS", "NLCINDIA.NS", "CESC.NS",
    # Oil & Gas
    "ONGC.NS", "IOC.NS", "GAIL.NS", "PETRONET.NS", "OIL.NS",
    # Metals & Mining
    "TATASTEEL.NS", "SAIL.NS", "NMDC.NS", "VEDL.NS", "NATIONALUM.NS",
    # Railway & Infra
    "RVNL.NS", "IRFC.NS", "IRCON.NS", "NBCC.NS", "HUDCO.NS",
    # Auto Ancillary
    "MOTHERSON.NS", "CASTROLIND.NS", "EXIDEIND.NS", "ARE&M.NS",
    # IT & Telecom
    "WIPRO.NS", "HFCL.NS", "FSL.NS", "ITI.NS",
    # Pharma
    "PIRPHARMA.NS", "BIOCON.NS", "GLENMARK.NS",
    # Capital Goods & Defense
    "BEL.NS", "BHEL.NS",
    # Finance & Logistics
    "MANAPPURAM.NS", "REDINGTON.NS", "IDFC.NS",
    # Textiles & Real Estate
    "TRIDENT.NS", "ALOKINDS.NS",
    # Fertilizer & Chemicals
    "GSFC.NS", "GNFC.NS", "FACT.NS", "RCF.NS", "NFL.NS"
]

TOTAL_CAPITAL = 50000.0
MAX_ACTIVE_TRADES = 4
CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES

def is_market_open(now_time):
    start_time = time(9, 15)
    end_time = time(15, 30)
    return start_time <= now_time.time() <= end_time

def calculate_vwap(df):
    v = df['Volume'].values
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * v).cumsum() / v.cumsum()

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# -----------------------------------------------------------------------------
# REAL-TIME LIVE SCANNER LOGIC
# -----------------------------------------------------------------------------
def fetch_live_signals():
    all_signals = []

    for symbol in UNDER_300_WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            # Direct Real-Time 5m Data Fetch
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 20:
                continue

            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)
            df['ATR'] = calculate_atr(df, period=14)

            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            ema20 = df["EMA20"].values
            vwap = df["VWAP"].values
            atrs = df["ATR"].values
            timestamps = df.index
            
            # Real-time Last CMP
            cmp_price = round(float(closes[-1]), 2)

            for i in range(20, len(df)):
                candle_time_str = timestamps[i].strftime("%H:%M")
                
                if candle_time_str >= "15:15":
                    break

                curr_close = closes[i]
                curr_high = highs[i]
                curr_low = lows[i]
                curr_ema = ema20[i]
                curr_vwap = vwap[i]
                curr_atr = atrs[i]

                if np.isnan(curr_atr) or curr_atr == 0:
                    curr_atr = curr_close * 0.005

                bullish_trend = curr_ema > curr_vwap
                long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                bearish_trend = curr_ema < curr_vwap
                short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if long_pullback or short_pullback:
                    trade_type = "BUY 🟢" if long_pullback else "SELL 🔴"
                    entry = round(float(curr_close), 2)
                    qty = max(1, int(CAPITAL_PER_STOCK / entry))

                    # REAL DYNAMIC BUFFER ATR LOGIC
                    sl_dist = round(float(curr_atr + (entry * 0.0025)), 2)
                    target_dist = round(float(sl_dist * 1.20), 2)

                    if long_pullback:
                        sl = round(entry - sl_dist, 2)
                        target = round(entry + target_dist, 2)
                    else:
                        sl = round(entry + sl_dist, 2)
                        target = round(entry - target_dist, 2)

                    status = "LIVE 🟡"
                    pnl = round((cmp_price - entry) * qty, 2) if long_pullback else round((entry - cmp_price) * qty, 2)

                    # Check historical progression inside today's session
                    for j in range(i + 1, len(df)):
                        check_time_str = timestamps[j].strftime("%H:%M")

                        if long_pullback and highs[j] >= target:
                            status = "TARGET 🟢"
                            pnl = round(target_dist * qty, 2)
                            break
                        elif not long_pullback and lows[j] <= target:
                            status = "TARGET 🟢"
                            pnl = round(target_dist * qty, 2)
                            break

                        if long_pullback and lows[j] <= sl:
                            status = "SL HIT 🔴"
                            pnl = round(-sl_dist * qty, 2)
                            break
                        elif not long_pullback and highs[j] >= sl:
                            status = "SL HIT 🔴"
                            pnl = round(-sl_dist * qty, 2)
                            break

                        if check_time_str >= "15:20":
                            status = "AUTO SQ OFF ⚪"
                            exit_price = round(float(closes[j]), 2)
                            pnl = round((exit_price - entry) * qty, 2) if long_pullback else round((entry - exit_price) * qty, 2)
                            break

                    all_signals.append({
                        "Time": candle_time_str,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": trade_type,
                        "Qty": qty,
                        "Entry Price": entry,
                        "Stop Loss (SL)": sl,
                        "Target": target,
                        "CMP": cmp_price,
                        "Status": status,
                        "P&L (₹)": pnl
                    })

                    break

        except Exception:
            continue

    return pd.DataFrame(all_signals)

# -----------------------------------------------------------------------------
# REAL-TIME RENDER (Auto-Refresh Every 10 Seconds)
# -----------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_date = now_ist.strftime("%Y-%m-%d")
    current_time = now_ist.strftime("%H:%M:%S")

    market_active = is_market_open(now_ist)
    status_text = "🟢 SCANNING REAL LIVE MARKET" if market_active else "🔴 MARKET CLOSED (REAL-TIME POSITIONS FIXED)"

    df_signals = fetch_live_signals()

    if not df_signals.empty:
        total_trades = len(df_signals)
        live_trades = len(df_signals[df_signals["Status"] == "LIVE 🟡"])
        targets_hit = len(df_signals[df_signals["Status"] == "TARGET 🟢"])
        sl_hit = len(df_signals[df_signals["Status"] == "SL HIT 🔴"])
        
        df_sq_off = df_signals[df_signals["Status"] == "AUTO SQ OFF ⚪"]
        auto_sq_off_count = len(df_sq_off)
        auto_sq_off_pnl = round(df_sq_off["P&L (₹)"].sum(), 2) if not df_sq_off.empty else 0.0

        overall_pnl = round(df_signals["P&L (₹)"].sum(), 2)
    else:
        total_trades = 0
        live_trades = 0
        targets_hit = 0
        sl_hit = 0
        auto_sq_off_count = 0
        auto_sq_off_pnl = 0.0
        overall_pnl = 0.0

    pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"
    sq_off_pnl_color = "#4CAF50" if auto_sq_off_pnl >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {current_date} | <b>Time (IST):</b> {current_time}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            📊 <b>Cap:</b> ₹50k | <b>Active LIVE:</b> {live_trades} | <b>Total Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} <br>
            ⚪ <b>Auto Sq-Off Trades (3:20 PM):</b> {auto_sq_off_count} | <b>Sq-Off P&L:</b> <span style="color:{sq_off_pnl_color}; font-weight:bold;">₹{auto_sq_off_pnl}</span> | <b>Net Total P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">₹{overall_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Live Intraday Trade Terminal")

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
        st.info("Market open hone par live signals scan ho kar auto-appear honge.")

render_dashboard()
