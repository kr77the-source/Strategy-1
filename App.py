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
    page_title="Intraday Scanner (14 SL / 60 Target)", layout="wide"
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

st.markdown("### 🔴 LIVE INTRADAY DASHBOARD (All Stocks: 14 Pts SL | 60 Pts Target)")

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

def estimate_charges(entry_price, exit_price, qty):
    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover
    
    total_brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00025
    exchange_charges = total_turnover * 0.0000297
    gst = (total_brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_charges = total_turnover * 0.0000001
    
    return round(total_brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)

# -----------------------------------------------------------------------------
# REAL-TIME LIVE SCANNER LOGIC (STRICT 14 PTS SL / 60 PTS TARGET FOR ALL)
# -----------------------------------------------------------------------------
def fetch_live_signals():
    all_signals = []

    for symbol in UNDER_300_WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 20:
                continue

            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)

            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            ema20 = df["EMA20"].values
            vwap = df["VWAP"].values
            timestamps = df.index
            
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

                bullish_trend = curr_ema > curr_vwap
                long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                bearish_trend = curr_ema < curr_vwap
                short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if long_pullback or short_pullback:
                    trade_type = "BUY 🟢" if long_pullback else "SELL 🔴"
                    entry = round(float(curr_close), 2)
                    qty = max(1, int(CAPITAL_PER_STOCK / entry))

                    # STRICT 14 POINTS SL AND 60 POINTS TARGET FOR ALL STOCKS
                    sl_dist = 14.0
                    target_dist = 60.0

                    if long_pullback:
                        sl = round(entry - sl_dist, 2)
                        target = round(entry + target_dist, 2)
                    else:
                        sl = round(entry + sl_dist, 2)
                        target = round(entry - target_dist, 2)

                    status = "LIVE 🟡"
                    exit_price = cmp_price
                    gross_pnl = round((cmp_price - entry) * qty, 2) if long_pullback else round((entry - cmp_price) * qty, 2)

                    for j in range(i + 1, len(df)):
                        check_time_str = timestamps[j].strftime("%H:%M")

                        if long_pullback and highs[j] >= target:
                            status = "TARGET 🟢"
                            exit_price = target
                            gross_pnl = round(target_dist * qty, 2)
                            break
                        elif not long_pullback and lows[j] <= target:
                            status = "TARGET 🟢"
                            exit_price = target
                            gross_pnl = round(target_dist * qty, 2)
                            break

                        if long_pullback and lows[j] <= sl:
                            status = "SL HIT 🔴"
                            exit_price = sl
                            gross_pnl = round(-sl_dist * qty, 2)
                            break
                        elif not long_pullback and highs[j] >= sl:
                            status = "SL HIT 🔴"
                            exit_price = sl
                            gross_pnl = round(-sl_dist * qty, 2)
                            break

                        if check_time_str >= "15:20":
                            status = "AUTO SQ OFF ⚪"
                            exit_price = round(float(closes[j]), 2)
                            gross_pnl = round((exit_price - entry) * qty, 2) if long_pullback else round((entry - exit_price) * qty, 2)
                            break

                    est_tax = estimate_charges(entry, exit_price, qty)
                    net_pnl = round(gross_pnl - est_tax, 2)

                    all_signals.append({
                        "Time": candle_time_str,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": trade_type,
                        "Qty": qty,
                        "Entry": entry,
                        "SL (14 Pts)": sl,
                        "Target (60 Pts)": target,
                        "CMP/Exit": exit_price,
                        "Status": status,
                        "Gross P&L (₹)": gross_pnl,
                        "Tax/Charges (₹)": est_tax,
                        "Net P&L (₹)": net_pnl
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
    status_text = "🟢 SCANNING REAL LIVE MARKET" if market_active else "🔴 MARKET CLOSED"

    df_signals = fetch_live_signals()

    if not df_signals.empty:
        total_trades = len(df_signals)
        live_trades = len(df_signals[df_signals["Status"] == "LIVE 🟡"])
        targets_hit = len(df_signals[df_signals["Status"] == "TARGET 🟢"])
        sl_hit = len(df_signals[df_signals["Status"] == "SL HIT 🔴"])
        
        total_gross_pnl = round(df_signals["Gross P&L (₹)"].sum(), 2)
        total_charges = round(df_signals["Tax/Charges (₹)"].sum(), 2)
        total_net_pnl = round(df_signals["Net P&L (₹)"].sum(), 2)
    else:
        total_trades = 0
        live_trades = 0
        targets_hit = 0
        sl_hit = 0
        total_gross_pnl = 0.0
        total_charges = 0.0
        total_net_pnl = 0.0

    gross_pnl_color = "#4CAF50" if total_gross_pnl >= 0 else "#FF5252"
    net_pnl_color = "#4CAF50" if total_net_pnl >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {current_date} | <b>Time (IST):</b> {current_time}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            📊 <b>Cap:</b> ₹50k | <b>Active LIVE:</b> {live_trades} | <b>Total Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} <br>
            💵 <b>Gross P&L:</b> <span style="color:{gross_pnl_color}; font-weight:bold;">₹{total_gross_pnl}</span> | 
            🧾 <b>Est. Taxes & Charges:</b> <span style="color:#FF9800; font-weight:bold;">₹{total_charges}</span> | 
            🎯 <b>NET IN-HAND P&L:</b> <span style="color:{net_pnl_color}; font-weight:bold;">₹{total_net_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Live Intraday Trade Terminal (Strict 14 SL / 60 Target)")

    if not df_signals.empty:
        st.dataframe(
            df_signals[
                [
                    "Time",
                    "Symbol",
                    "Type",
                    "Qty",
                    "Entry",
                    "SL (14 Pts)",
                    "Target (60 Pts)",
                    "CMP/Exit",
                    "Status",
                    "Gross P&L (₹)",
                    "Tax/Charges (₹)",
                    "Net P&L (₹)"
                ]
            ],
            use_container_width=True,
        )
    else:
        st.info("Market open hone par live signals scan ho kar auto-appear honge.")

render_dashboard()
