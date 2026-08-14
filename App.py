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
    page_title="Intraday Scanner (% based SL/Target)", layout="wide"
)

st.markdown("""
    <style>
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    header[data-testid="stHeader"] { background: transparent; }
    h3 {
        font-size: 1.1rem !important;
        margin-top: 0rem !important;
        margin-bottom: 0.5rem !important;
        padding: 0px !important;
    }
    .status-card, .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 6px 10px;
        color: #ffffff;
        font-size: 12px;
        margin-bottom: 5px;
    }
    hr { margin-top: 0.3rem !important; margin-bottom: 0.3rem !important; }
    </style>
""", unsafe_allow_html=True)

st.markdown("### ðŸ”´ LIVE INTRADAY DASHBOARD (% based SL / Target)")

# -----------------------------------------------------------------------------
# WATCHLIST
# -----------------------------------------------------------------------------
UNDER_300_WATCHLIST = [
    "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "UNIONBANK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS",
    "POWERGRID.NS", "NHPC.NS", "SJVN.NS", "NLCINDIA.NS", "CESC.NS",
    "ONGC.NS", "IOC.NS", "GAIL.NS", "PETRONET.NS", "OIL.NS",
    "TATASTEEL.NS", "SAIL.NS", "NMDC.NS", "VEDL.NS", "NATIONALUM.NS",
    "RVNL.NS", "IRFC.NS", "IRCON.NS", "NBCC.NS", "HUDCO.NS",
    "MOTHERSON.NS", "CASTROLIND.NS", "EXIDEIND.NS",
    "WIPRO.NS", "HFCL.NS", "FSL.NS", "ITI.NS",
    "BIOCON.NS", "GLENMARK.NS",
    "BEL.NS", "BHEL.NS",
    "MANAPPURAM.NS", "REDINGTON.NS", "IDFC.NS",
    "TRIDENT.NS",
    "GSFC.NS", "GNFC.NS", "FACT.NS", "RCF.NS", "NFL.NS"
]

# -----------------------------------------------------------------------------
# SIDEBAR SETTINGS (fully adjustable â€” no more hardcoded 14/25 points)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("âš™ï¸ Settings")
    TOTAL_CAPITAL = st.number_input("Total Capital (â‚¹)", value=50000, step=5000)
    MAX_ACTIVE_TRADES = st.number_input("Max Active Trades", value=4, min_value=1, max_value=10)
    SL_PCT = st.number_input("Stop Loss (%)", value=0.6, step=0.1, format="%.2f") / 100
    TARGET_PCT = st.number_input("Target (%)", value=1.1, step=0.1, format="%.2f") / 100
    st.caption(f"Risk:Reward â‰ˆ 1 : {round(TARGET_PCT/SL_PCT, 2)}")
    if st.button("ðŸ”„ Reset today's signals"):
        st.session_state.trade_log = {}
        st.session_state.processed_keys = set()

CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES

# -----------------------------------------------------------------------------
# SESSION STATE (persists across the 10s auto-refresh â€” this is what makes it
# genuinely "live" instead of re-simulating the whole day every run)
# -----------------------------------------------------------------------------
if "trade_log" not in st.session_state:
    st.session_state.trade_log = {}       # key -> trade dict
if "processed_keys" not in st.session_state:
    st.session_state.processed_keys = set()  # candle keys already checked for new signals


def is_market_open(now_dt):
    start_time, end_time = time(9, 15), time(15, 30)
    return start_time <= now_dt.time() <= end_time


def calculate_vwap(df):
    v = df["Volume"].values
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * v).cumsum() / np.maximum(v.cumsum(), 1)


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
# BATCH FETCH (single call for all symbols instead of 50 separate requests)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=10, show_spinner=False)
def fetch_all_data():
    try:
        data = yf.download(
            tickers=" ".join(UNDER_300_WATCHLIST),
            period="1d",
            interval="5m",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return {}

    result = {}
    for symbol in UNDER_300_WATCHLIST:
        try:
            df = data[symbol].dropna(how="all") if len(UNDER_300_WATCHLIST) > 1 else data
            if df is not None and not df.empty and len(df) >= 20:
                result[symbol] = df
        except Exception:
            continue
    return result


def count_live_trades():
    return sum(1 for t in st.session_state.trade_log.values() if t["Status"] == "LIVE ðŸŸ¡")


# -----------------------------------------------------------------------------
# SIGNAL DETECTION + LIVE TRADE UPDATE
# -----------------------------------------------------------------------------
def scan_and_update():
    all_data = fetch_all_data()

    for symbol, df in all_data.items():
        try:
            df = df.copy()
            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["VWAP"] = calculate_vwap(df)

            closes, highs, lows = df["Close"].values, df["High"].values, df["Low"].values
            ema20, vwap = df["EMA20"].values, df["VWAP"].values
            timestamps = df.index

            # --- 1. Update any already-LIVE trades for this symbol with new candles ---
            for key, trade in list(st.session_state.trade_log.items()):
                if trade["SymbolRaw"] != symbol or trade["Status"] != "LIVE ðŸŸ¡":
                    continue

                entry_idx = trade["EntryIdx"]
                is_long = trade["IsLong"]
                sl, target = trade["SL"], trade["Target"]

                for j in range(entry_idx + 1, len(df)):
                    t_str = timestamps[j].strftime("%H:%M")
                    hit_target = (is_long and highs[j] >= target) or (not is_long and lows[j] <= target)
                    hit_sl = (is_long and lows[j] <= sl) or (not is_long and highs[j] >= sl)

                    if hit_target:
                        trade["Status"] = "TARGET ðŸŸ¢"
                        trade["CMP/Exit"] = target
                        break
                    if hit_sl:
                        trade["Status"] = "SL HIT ðŸ”´"
                        trade["CMP/Exit"] = sl
                        break
                    if t_str >= "15:20":
                        trade["Status"] = "AUTO SQ OFF âšª"
                        trade["CMP/Exit"] = round(float(closes[j]), 2)
                        break
                else:
                    # still open, mark last close as running CMP
                    trade["CMP/Exit"] = round(float(closes[-1]), 2)

                if trade["Status"] != "LIVE ðŸŸ¡":
                    gross = (
                        round((trade["CMP/Exit"] - trade["Entry"]) * trade["Qty"], 2)
                        if is_long
                        else round((trade["Entry"] - trade["CMP/Exit"]) * trade["Qty"], 2)
                    )
                    est_tax = estimate_charges(trade["Entry"], trade["CMP/Exit"], trade["Qty"])
                    trade["Gross P&L (â‚¹)"] = gross
                    trade["Tax/Charges (â‚¹)"] = est_tax
                    trade["Net P&L (â‚¹)"] = round(gross - est_tax, 2)
                else:
                    gross = (
                        round((trade["CMP/Exit"] - trade["Entry"]) * trade["Qty"], 2)
                        if is_long
                        else round((trade["Entry"] - trade["CMP/Exit"]) * trade["Qty"], 2)
                    )
                    trade["Gross P&L (â‚¹)"] = gross
                    trade["Tax/Charges (â‚¹)"] = "-"
                    trade["Net P&L (â‚¹)"] = "-"

            # --- 2. Look for NEW signals on candles not yet processed ---
            for i in range(20, len(df)):
                t_str = timestamps[i].strftime("%H:%M")
                if t_str >= "15:15":
                    break

                candle_key = f"{symbol}_{timestamps[i].isoformat()}"
                if candle_key in st.session_state.processed_keys:
                    continue
                st.session_state.processed_keys.add(candle_key)

                curr_close, curr_high, curr_low = closes[i], highs[i], lows[i]
                curr_ema, curr_vwap = ema20[i], vwap[i]

                bullish = curr_ema > curr_vwap
                long_pullback = bullish and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                bearish = curr_ema < curr_vwap
                short_pullback = bearish and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if not (long_pullback or short_pullback):
                    continue

                # enforce capital / max-active-trades cap
                if count_live_trades() >= MAX_ACTIVE_TRADES:
                    continue  # skip taking this trade â€” capital already deployed

                is_long = long_pullback
                entry = round(float(curr_close), 2)
                qty = max(1, int(CAPITAL_PER_STOCK / entry))

                sl = round(entry - entry * SL_PCT, 2) if is_long else round(entry + entry * SL_PCT, 2)
                target = round(entry + entry * TARGET_PCT, 2) if is_long else round(entry - entry * TARGET_PCT, 2)

                st.session_state.trade_log[candle_key] = {
                    "SymbolRaw": symbol,
                    "EntryIdx": i,
                    "IsLong": is_long,
                    "Time": t_str,
                    "Symbol": symbol.replace(".NS", ""),
                    "Type": "BUY ðŸŸ¢" if is_long else "SELL ðŸ”´",
                    "Qty": qty,
                    "Entry": entry,
                    "SL": sl,
                    "Target": target,
                    "Status": "LIVE ðŸŸ¡",
                    "CMP/Exit": entry,
                    "Gross P&L (â‚¹)": 0.0,
                    "Tax/Charges (â‚¹)": "-",
                    "Net P&L (â‚¹)": "-",
                }
        except Exception:
            continue


# -----------------------------------------------------------------------------
# RENDER (auto-refresh every 10 seconds)
# -----------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    market_active = is_market_open(now_ist)
    status_text = "ðŸŸ¢ SCANNING REAL LIVE MARKET" if market_active else "ðŸ”´ MARKET CLOSED"

    if market_active:
        scan_and_update()

    trades = list(st.session_state.trade_log.values())
    df_signals = pd.DataFrame(trades)

    if not df_signals.empty:
        total_trades = len(df_signals)
        live_trades = len(df_signals[df_signals["Status"] == "LIVE ðŸŸ¡"])
        targets_hit = len(df_signals[df_signals["Status"] == "TARGET ðŸŸ¢"])
        sl_hit = len(df_signals[df_signals["Status"] == "SL HIT ðŸ”´"])

        closed = df_signals[df_signals["Status"] != "LIVE ðŸŸ¡"]
        total_gross_pnl = round(pd.to_numeric(closed["Gross P&L (â‚¹)"], errors="coerce").sum(), 2) if not closed.empty else 0.0
        total_charges = round(pd.to_numeric(closed["Tax/Charges (â‚¹)"], errors="coerce").sum(), 2) if not closed.empty else 0.0
        total_net_pnl = round(pd.to_numeric(closed["Net P&L (â‚¹)"], errors="coerce").sum(), 2) if not closed.empty else 0.0
    else:
        total_trades = live_trades = targets_hit = sl_hit = 0
        total_gross_pnl = total_charges = total_net_pnl = 0.0

    gross_color = "#4CAF50" if total_gross_pnl >= 0 else "#FF5252"
    net_color = "#4CAF50" if total_net_pnl >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {now_ist.strftime("%Y-%m-%d")} | <b>Time (IST):</b> {now_ist.strftime("%H:%M:%S")}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            ðŸ“Š <b>Cap:</b> â‚¹{int(TOTAL_CAPITAL):,} | <b>Active LIVE:</b> {live_trades}/{MAX_ACTIVE_TRADES} | <b>Total Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} <br>
            ðŸ’µ <b>Gross P&L (closed):</b> <span style="color:{gross_color}; font-weight:bold;">â‚¹{total_gross_pnl}</span> |
            ðŸ§¾ <b>Est. Taxes:</b> <span style="color:#FF9800; font-weight:bold;">â‚¹{total_charges}</span> |
            ðŸŽ¯ <b>NET P&L:</b> <span style="color:{net_color}; font-weight:bold;">â‚¹{total_net_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### ðŸ“‹ Live Intraday Trade Terminal")

    if not df_signals.empty:
        display_cols = [
            "Time", "Symbol", "Type", "Qty", "Entry", "SL", "Target",
            "CMP/Exit", "Status", "Gross P&L (â‚¹)", "Tax/Charges (â‚¹)", "Net P&L (â‚¹)"
        ]
        st.dataframe(df_signals[display_cols].iloc[::-1], use_container_width=True)
    else:
        st.info("Market open hone par live signals scan ho kar auto-appear honge.")


render_dashboard()
