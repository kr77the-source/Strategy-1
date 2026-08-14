import os
from datetime import datetime, time
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Intraday Scanner (% based SL/Target)", layout="wide")

# NOTE: no raw emoji characters used anywhere below — CSS badges instead.
# This avoids the mojibake / garbled-text issue some deployments show with
# multi-byte unicode (emoji, rupee symbol) inside f-strings.
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
    .badge {
        display: inline-block;
        padding: 1px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 11px;
    }
    .badge-live   { background-color: #FFC10730; color: #FFC107; }
    .badge-target { background-color: #4CAF5030; color: #4CAF50; }
    .badge-sl     { background-color: #FF525230; color: #FF5252; }
    .badge-sqoff  { background-color: #90A4AE30; color: #CFD8DC; }
    .badge-buy    { background-color: #4CAF5030; color: #4CAF50; }
    .badge-sell   { background-color: #FF525230; color: #FF5252; }
    </style>
""", unsafe_allow_html=True)

st.markdown("### LIVE INTRADAY DASHBOARD (% based SL / Target)")

RUPEE = "&#8377;"  # HTML entity, safe across all encodings

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
# PERSISTENT STORAGE (CSV) — survives app restarts/sleep, unlike session_state
# NOTE: on Streamlit Community Cloud the disk resets on a fresh redeploy.
# For guaranteed permanent history across redeploys, replace this with a
# Google Sheet or a hosted DB (Supabase/Postgres). For day-to-day persistence
# while the app stays deployed, this CSV approach works.
# -----------------------------------------------------------------------------
HISTORY_FILE = "trade_history.csv"
HISTORY_COLUMNS = [
    "Date", "Time", "Symbol", "Type", "Qty", "Entry", "SL", "Target",
    "Exit", "Status", "GrossPnL", "Charges", "NetPnL"
]


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return pd.read_csv(HISTORY_FILE)
        except Exception:
            return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def append_history(row: dict):
    df = load_history()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(HISTORY_FILE, index=False)


# -----------------------------------------------------------------------------
# SIDEBAR SETTINGS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")
    TOTAL_CAPITAL = st.number_input("Total Capital (Rs)", value=50000, step=5000)
    MAX_ACTIVE_TRADES = st.number_input("Max Active Trades", value=4, min_value=1, max_value=10)
    SL_PCT = st.number_input("Stop Loss (%)", value=0.6, step=0.1, format="%.2f") / 100
    TARGET_PCT = st.number_input("Target (%)", value=1.1, step=0.1, format="%.2f") / 100
    st.caption(f"Risk:Reward approx 1 : {round(TARGET_PCT/SL_PCT, 2)}")

    if st.button("Reset TODAY's live signals (keeps history file)"):
        st.session_state.trade_log = {}
        st.session_state.processed_keys = set()

    if st.button("Delete ALL saved history (irreversible)"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.session_state.trade_log = {}
        st.session_state.processed_keys = set()

CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES

# -----------------------------------------------------------------------------
# SESSION STATE
# -----------------------------------------------------------------------------
if "trade_log" not in st.session_state:
    st.session_state.trade_log = {}
if "processed_keys" not in st.session_state:
    st.session_state.processed_keys = set()


def is_market_open(now_dt):
    return time(9, 15) <= now_dt.time() <= time(15, 30)


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


@st.cache_data(ttl=10, show_spinner=False)
def fetch_all_data():
    try:
        data = yf.download(
            tickers=" ".join(UNDER_300_WATCHLIST),
            period="1d", interval="5m", group_by="ticker",
            threads=True, progress=False, auto_adjust=False,
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
    return sum(1 for t in st.session_state.trade_log.values() if t["Status"] == "LIVE")


def badge(text, cls):
    return f'<span class="badge {cls}">{text}</span>'


STATUS_BADGE = {
    "LIVE": ("LIVE", "badge-live"),
    "TARGET": ("TARGET HIT", "badge-target"),
    "SL": ("SL HIT", "badge-sl"),
    "SQOFF": ("AUTO SQ-OFF", "badge-sqoff"),
}


def scan_and_update():
    all_data = fetch_all_data()
    today_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    for symbol, df in all_data.items():
        try:
            df = df.copy()
            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["VWAP"] = calculate_vwap(df)

            closes, highs, lows = df["Close"].values, df["High"].values, df["Low"].values
            ema20, vwap = df["EMA20"].values, df["VWAP"].values
            timestamps = df.index

            # Update LIVE trades
            for key, trade in list(st.session_state.trade_log.items()):
                if trade["SymbolRaw"] != symbol or trade["Status"] != "LIVE":
                    continue

                entry_idx, is_long = trade["EntryIdx"], trade["IsLong"]
                sl, target = trade["SL"], trade["Target"]
                closed_now = False

                for j in range(entry_idx + 1, len(df)):
                    t_str = timestamps[j].strftime("%H:%M")
                    hit_target = (is_long and highs[j] >= target) or (not is_long and lows[j] <= target)
                    hit_sl = (is_long and lows[j] <= sl) or (not is_long and highs[j] >= sl)

                    if hit_target:
                        trade["Status"], trade["CMP/Exit"], closed_now = "TARGET", target, True
                        break
                    if hit_sl:
                        trade["Status"], trade["CMP/Exit"], closed_now = "SL", sl, True
                        break
                    if t_str >= "15:20":
                        trade["Status"] = "SQOFF"
                        trade["CMP/Exit"] = round(float(closes[j]), 2)
                        closed_now = True
                        break
                else:
                    trade["CMP/Exit"] = round(float(closes[-1]), 2)

                gross = (
                    round((trade["CMP/Exit"] - trade["Entry"]) * trade["Qty"], 2) if is_long
                    else round((trade["Entry"] - trade["CMP/Exit"]) * trade["Qty"], 2)
                )
                trade["Gross P&L"] = gross

                if closed_now:
                    est_tax = estimate_charges(trade["Entry"], trade["CMP/Exit"], trade["Qty"])
                    net = round(gross - est_tax, 2)
                    trade["Tax"] = est_tax
                    trade["Net P&L"] = net
                    append_history({
                        "Date": today_str, "Time": trade["Time"], "Symbol": trade["Symbol"],
                        "Type": trade["TypeLabel"], "Qty": trade["Qty"], "Entry": trade["Entry"],
                        "SL": sl, "Target": target, "Exit": trade["CMP/Exit"],
                        "Status": trade["Status"], "GrossPnL": gross, "Charges": est_tax, "NetPnL": net,
                    })
                else:
                    trade["Tax"], trade["Net P&L"] = None, None

            # Detect NEW signals
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
                if count_live_trades() >= MAX_ACTIVE_TRADES:
                    continue

                is_long = long_pullback
                entry = round(float(curr_close), 2)
                qty = max(1, int(CAPITAL_PER_STOCK / entry))
                sl = round(entry - entry * SL_PCT, 2) if is_long else round(entry + entry * SL_PCT, 2)
                target = round(entry + entry * TARGET_PCT, 2) if is_long else round(entry - entry * TARGET_PCT, 2)

                st.session_state.trade_log[candle_key] = {
                    "SymbolRaw": symbol, "EntryIdx": i, "IsLong": is_long,
                    "Time": t_str, "Symbol": symbol.replace(".NS", ""),
                    "TypeLabel": "BUY" if is_long else "SELL",
                    "Qty": qty, "Entry": entry, "SL": sl, "Target": target,
                    "Status": "LIVE", "CMP/Exit": entry,
                    "Gross P&L": 0.0, "Tax": None, "Net P&L": None,
                }
        except Exception:
            continue


@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    today_str = now_ist.strftime("%Y-%m-%d")
    market_active = is_market_open(now_ist)
    status_text = "SCANNING LIVE MARKET" if market_active else "MARKET CLOSED"

    if market_active:
        scan_and_update()

    live_trades_list = list(st.session_state.trade_log.values())
    live_count = count_live_trades()

    history_df = load_history()
    today_df = history_df[history_df["Date"] == today_str] if not history_df.empty else history_df

    today_targets = len(today_df[today_df["Status"] == "TARGET"]) if not today_df.empty else 0
    today_sl = len(today_df[today_df["Status"] == "SL"]) if not today_df.empty else 0
    today_net = round(today_df["NetPnL"].sum(), 2) if not today_df.empty else 0.0
    today_gross = round(today_df["GrossPnL"].sum(), 2) if not today_df.empty else 0.0
    today_charges = round(today_df["Charges"].sum(), 2) if not today_df.empty else 0.0

    alltime_targets = len(history_df[history_df["Status"] == "TARGET"]) if not history_df.empty else 0
    alltime_sl = len(history_df[history_df["Status"] == "SL"]) if not history_df.empty else 0
    alltime_net = round(history_df["NetPnL"].sum(), 2) if not history_df.empty else 0.0
    alltime_trades = len(history_df) if not history_df.empty else 0

    net_color_today = "#4CAF50" if today_net >= 0 else "#FF5252"
    net_color_all = "#4CAF50" if alltime_net >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {today_str} | <b>Time (IST):</b> {now_ist.strftime("%H:%M:%S")}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            <b>Capital:</b> {RUPEE}{int(TOTAL_CAPITAL):,} | <b>Active LIVE:</b> {live_count}/{MAX_ACTIVE_TRADES}<br><br>
            <b>TODAY</b> &mdash; Trades: {len(today_df)} | Targets: {today_targets} | SL: {today_sl}<br>
            Gross: <span style="color:{net_color_today};">{RUPEE}{today_gross}</span> |
            Charges: <span style="color:#FF9800;">{RUPEE}{today_charges}</span> |
            Net: <span style="color:{net_color_today}; font-weight:bold;">{RUPEE}{today_net}</span><br><br>
            <b>ALL-TIME (saved history)</b> &mdash; Trades: {alltime_trades} | Targets: {alltime_targets} | SL: {alltime_sl} |
            Net: <span style="color:{net_color_all}; font-weight:bold;">{RUPEE}{alltime_net}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### Live Intraday Trade Terminal (today, in-progress + closed)")

    if live_trades_list:
        rows = []
        for t in reversed(live_trades_list):
            label, cls = STATUS_BADGE[t["Status"]]
            type_cls = "badge-buy" if t["TypeLabel"] == "BUY" else "badge-sell"
            rows.append({
                "Time": t["Time"],
                "Symbol": t["Symbol"],
                "Type": badge(t["TypeLabel"], type_cls),
                "Qty": t["Qty"],
                "Entry": t["Entry"],
                "SL": t["SL"],
                "Target": t["Target"],
                "CMP/Exit": t["CMP/Exit"],
                "Status": badge(label, cls),
                "Gross P&L": t["Gross P&L"],
                "Net P&L": t["Net P&L"] if t["Net P&L"] is not None else "-",
            })
        display_df = pd.DataFrame(rows)
        st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Market open hone par live signals scan ho kar auto-appear honge.")

    with st.expander("Full saved trade history (all days)"):
        if not history_df.empty:
            st.dataframe(history_df.iloc[::-1], use_container_width=True)
            st.download_button(
                "Download full history CSV",
                data=history_df.to_csv(index=False),
                file_name="trade_history.csv",
                mime="text/csv",
            )
        else:
            st.caption("Abhi koi closed trade save nahi hui hai.")


render_dashboard()
