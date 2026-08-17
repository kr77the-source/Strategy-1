import os
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG & STYLES
# -----------------------------------------------------------------------------
st.set_page_config(page_title="EMA Backtest & Live Terminal", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 3.5rem !important; padding-bottom: 0rem !important; padding-left: 1rem !important; padding-right: 1rem !important; }
    header[data-testid="stHeader"] { background: transparent; }
    .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 8px 12px;
        color: #ffffff;
        font-size: 13px;
        margin-bottom: 8px;
    }
    </style>
""", unsafe_allow_html=True)

RUPEE = "&#8377;"

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

HISTORY_FILE = "strategy_history_db.csv"
HISTORY_COLUMNS = [
    "Date", "Time", "Symbol", "StrategyMode", "Type", "Qty", "Entry", "SL",
    "Exit", "Status", "GrossPnL", "Charges", "NetPnL"
]

# -----------------------------------------------------------------------------
# PERSISTENCE & HELPERS
# -----------------------------------------------------------------------------
def load_db():
    if os.path.exists(HISTORY_FILE):
        try:
            return pd.read_csv(HISTORY_FILE)
        except Exception:
            return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.DataFrame(columns=HISTORY_COLUMNS)

def append_db(row: dict):
    df = load_db()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(HISTORY_FILE, index=False)

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def estimate_charges(entry_price, exit_price, qty):
    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover
    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00025
    exchange_charges = total_turnover * 0.0000297
    gst = (brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_charges = total_turnover * 0.000001
    return round(brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)

# -----------------------------------------------------------------------------
# SIDEBAR: DYNAMIC CUSTOM SHARE ADDITION & PARAMETERS
# -----------------------------------------------------------------------------
if "watchlist" not in st.session_state:
    st.session_state.watchlist = DEFAULT_STOCKS.copy()

with st.sidebar:
    st.header("🔍 Dynamic Share Selection")
    
    # Custom Stock Input Section
    new_stock = st.text_input("Add Custom NSE Ticker (e.g. ZOMATO, TATAPOWER):", "").strip().upper()
    if st.button("➕ Add Share to Watchlist"):
        if new_stock:
            formatted_symbol = new_stock if new_stock.endswith(".NS") else f"{new_stock}.NS"
            if formatted_symbol not in st.session_state.watchlist:
                st.session_state.watchlist.append(formatted_symbol)
                st.success(f"{formatted_symbol} added!")
                st.rerun()

    SELECTED_STOCKS = st.multiselect(
        "Active Live/Backtest Watchlist (Max 10):",
        options=st.session_state.watchlist,
        default=st.session_state.watchlist[:5],
        max_selections=10
    )

    st.markdown("---")
    st.header("⚙️ Strategy Parameters")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=20, step=5)
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=50, step=5)
    USE_ATR_STOP = st.checkbox("Use ATR Stop Loss", value=True)
    ATR_LEN = st.number_input("ATR Length", value=14, step=1)
    ATR_MULT = st.number_input("ATR Multiplier", value=3.0, step=0.5)

    st.subheader("💰 Execution Settings")
    TRADE_VALUE = st.number_input("Trade Value per Stock (Rs)", value=3000, step=500)
    TIMEFRAME_MINS = st.selectbox("Candle Timeframe (Minutes)", [5, 15, 30, 60], index=1)

    st.markdown("---")
    st.header("🚀 Execution Mode")
    TRADING_MODE = st.radio("Select Mode:", ["Paper Trading / Backtest", "Live Signal Trigger"])

    if st.button("Clear Logs & Session"):
        st.session_state.normal_trades = {}
        st.session_state.reversal_trades = {}
        st.session_state.processed_keys = set()
        st.rerun()

if not SELECTED_STOCKS:
    st.warning("⚠️ Kam se kam 1 share select karein.")
    st.stop()

if "normal_trades" not in st.session_state:
    st.session_state.normal_trades = {}
if "reversal_trades" not in st.session_state:
    st.session_state.reversal_trades = {}
if "processed_keys" not in st.session_state:
    st.session_state.processed_keys = set()

# -----------------------------------------------------------------------------
# DATA ENGINE & PROCESSOR
# -----------------------------------------------------------------------------
@st.cache_data(ttl=15, show_spinner=False)
def fetch_market_data(stocks_list, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="5d", interval=tf_str, group_by="ticker", threads=True, progress=False)
        return data
    except Exception:
        return {}

def process_signals():
    data = fetch_market_data(SELECTED_STOCKS, TIMEFRAME_MINS)
    today_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    for symbol in SELECTED_STOCKS:
        try:
            df = data[symbol].dropna(how="all") if len(SELECTED_STOCKS) > 1 else data
            if df is None or len(df) < SLOW_MA_LEN:
                continue

            df = df.copy()
            df["FastEMA"] = calculate_ema(df["Close"], FAST_MA_LEN)
            df["SlowEMA"] = calculate_ema(df["Close"], SLOW_MA_LEN)
            df["ATR"] = calculate_atr(df, ATR_LEN)

            closes = df["Close"].values
            fast_ema, slow_ema, atr = df["FastEMA"].values, df["SlowEMA"].values, df["ATR"].values
            timestamps = df.index

            i = len(df) - 1
            candle_key = f"{symbol}_{timestamps[i].isoformat()}"
            t_str = timestamps[i].strftime("%H:%M")

            if candle_key not in st.session_state.processed_keys:
                st.session_state.processed_keys.add(candle_key)

                fast_curr, slow_curr = fast_ema[i], slow_ema[i]
                fast_prev, slow_prev = fast_ema[i-1], slow_ema[i-1]
                close_p, curr_atr = closes[i], atr[i]

                norm_signal = (fast_prev <= slow_prev and fast_curr > slow_curr) or (fast_curr > slow_curr)
                if norm_signal and symbol not in [t["SymbolRaw"] for t in st.session_state.normal_trades.values() if t["Status"] == "LIVE"]:
                    qty = max(1, int(TRADE_VALUE / close_p))
                    sl_p = close_p - (ATR_MULT * curr_atr) if USE_ATR_STOP and not np.isnan(curr_atr) else close_p * 0.95
                    st.session_state.normal_trades[f"NORM_{candle_key}"] = {
                        "SymbolRaw": symbol, "Symbol": symbol.replace(".NS", ""), "Time": t_str,
                        "Type": "BUY", "Qty": qty, "Entry": round(close_p, 2), "SL": round(sl_p, 2),
                        "Status": "LIVE", "Exit": round(close_p, 2), "GrossPnL": 0.0, "NetPnL": 0.0, "Mode": "Normal"
                    }

                rev_signal = (fast_prev >= slow_prev and fast_curr < slow_curr) or (fast_curr < slow_curr)
                if rev_signal and symbol not in [t["SymbolRaw"] for t in st.session_state.reversal_trades.values() if t["Status"] == "LIVE"]:
                    qty = max(1, int(TRADE_VALUE / close_p))
                    sl_p = close_p + (ATR_MULT * curr_atr) if USE_ATR_STOP and not np.isnan(curr_atr) else close_p * 1.05
                    st.session_state.reversal_trades[f"REV_{candle_key}"] = {
                        "SymbolRaw": symbol, "Symbol": symbol.replace(".NS", ""), "Time": t_str,
                        "Type": "SELL", "Qty": qty, "Entry": round(close_p, 2), "SL": round(sl_p, 2),
                        "Status": "LIVE", "Exit": round(close_p, 2), "GrossPnL": 0.0, "NetPnL": 0.0, "Mode": "Reversal"
                    }

            for trade_dict in [st.session_state.normal_trades, st.session_state.reversal_trades]:
                for k, t in list(trade_dict.items()):
                    if t["SymbolRaw"] == symbol and t["Status"] == "LIVE":
                        curr_close = closes[-1]
                        t["Exit"] = round(curr_close, 2)
                        is_long = t["Type"] == "BUY"

                        gross = (curr_close - t["Entry"]) * t["Qty"] if is_long else (t["Entry"] - curr_close) * t["Qty"]
                        t["GrossPnL"] = round(gross, 2)

                        hit_sl = (is_long and curr_close <= t["SL"]) or (not is_long and curr_close >= t["SL"])
                        if hit_sl:
                            t["Status"] = "SL HIT"
                            chg = estimate_charges(t["Entry"], curr_close, t["Qty"])
                            net = round(gross - chg, 2)
                            t["NetPnL"] = net
                            append_db({
                                "Date": today_str, "Time": t["Time"], "Symbol": t["Symbol"],
                                "StrategyMode": t["Mode"], "Type": t["Type"], "Qty": t["Qty"],
                                "Entry": t["Entry"], "SL": t["SL"], "Exit": t["Exit"],
                                "Status": "SL HIT", "GrossPnL": gross, "Charges": chg, "NetPnL": net
                            })
        except Exception:
            continue

# -----------------------------------------------------------------------------
# DUAL BACKTEST ENGINE (60 DAYS)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def run_60d_dual_backtest(stocks_list, fast_len, slow_len, atr_mult, use_atr, trade_val, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="60d", interval=tf_str, group_by="ticker", threads=True, progress=False)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    norm_list, rev_list = [], []

    for symbol in stocks_list:
        try:
            df = data[symbol].dropna(how="all") if len(stocks_list) > 1 else data
            if df is None or len(df) < slow_len:
                continue

            df = df.copy()
            df["FastEMA"] = calculate_ema(df["Close"], fast_len)
            df["SlowEMA"] = calculate_ema(df["Close"], slow_len)
            df["ATR"] = calculate_atr(df, 14)

            closes = df["Close"].values
            fast_ema, slow_ema, atr = df["FastEMA"].values, df["SlowEMA"].values, df["ATR"].values
            timestamps = df.index

            for i in range(slow_len, len(df)):
                fast_curr, slow_curr = fast_ema[i], slow_ema[i]
                fast_prev, slow_prev = fast_ema[i-1], slow_ema[i-1]
                entry_p, curr_atr = closes[i], atr[i]
                t_str = timestamps[i].strftime("%H:%M")
                date_str = timestamps[i].strftime("%Y-%m-%d")

                if fast_prev <= slow_prev and fast_curr > slow_curr:
                    qty = max(1, int(trade_val / entry_p))
                    exit_p = closes[min(i+5, len(df)-1)]
                    gross = round((exit_p - entry_p) * qty, 2)
                    chg = estimate_charges(entry_p, exit_p, qty)
                    norm_list.append({"Date": date_str, "Time": t_str, "Symbol": symbol.replace(".NS",""), "Type": "BUY", "Qty": qty, "Entry": round(entry_p, 2), "Exit": round(exit_p, 2), "GrossPnL": gross, "Charges": chg, "NetPnL": round(gross - chg, 2)})

                if fast_prev >= slow_prev and fast_curr < slow_curr:
                    qty = max(1, int(trade_val / entry_p))
                    exit_p = closes[min(i+5, len(df)-1)]
                    gross = round((entry_p - exit_p) * qty, 2)
                    chg = estimate_charges(entry_p, exit_p, qty)
                    rev_list.append({"Date": date_str, "Time": t_str, "Symbol": symbol.replace(".NS",""), "Type": "SELL", "Qty": qty, "Entry": round(entry_p, 2), "Exit": round(exit_p, 2), "GrossPnL": gross, "Charges": chg, "NetPnL": round(gross - chg, 2)})

        except Exception:
            continue

    return pd.DataFrame(norm_list), pd.DataFrame(rev_list)

# -----------------------------------------------------------------------------
# APP TABS & UI ROUTING
# -----------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "📊 Tab 1: 60-Day Backtest Analysis",
    "🟢 Tab 2: Live / Paper Normal Signals",
    "🔴 Tab 3: Live / Paper Reversal Signals"
])

process_signals()

with tab1:
    st.markdown(f"### 📊 Backtest Engine ({len(SELECTED_STOCKS)} Active Shares Selected)")
    st.info(f"Current Mode: **{TRADING_MODE}** | Selected Stocks: {', '.join([s.replace('.NS','') for s in SELECTED_STOCKS])}")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        run_btn = st.button("▶️ Run 60-Day Dual Backtest", type="primary")

    if run_btn:
        with st.spinner("Selected stocks par 60-day historical data process ho raha hai..."):
            norm_bt, rev_bt = run_60d_dual_backtest(SELECTED_STOCKS, FAST_MA_LEN, SLOW_MA_LEN, ATR_MULT, USE_ATR_STOP, TRADE_VALUE, TIMEFRAME_MINS)
            st.session_state.norm_bt = norm_bt
            st.session_state.rev_bt = rev_bt

    norm_bt = st.session_state.get("norm_bt")
    rev_bt = st.session_state.get("rev_bt")

    if norm_bt is not None and rev_bt is not None:
        c1, c2 = st.columns(2)

        def render_bt_summary(df, name):
            if df.empty:
                st.warning(f"No trades generated for {name}")
                return
            tot = len(df)
            wins = len(df[df["NetPnL"] > 0])
            wr = round((wins / tot) * 100, 1)
            net_pnl = round(df["NetPnL"].sum(), 2)
            charges = round(df["Charges"].sum(), 2)
            color = "#4CAF50" if net_pnl >= 0 else "#FF5252"

            st.markdown(f"#### {name}")
            st.markdown(f"""
                <div class="pnl-card">
                    <b>Total Trades:</b> {tot} | <b>Win Rate:</b> {wr}%<br>
                    <b>Total Charges:</b> {RUPEE}{charges}<br>
                    <b>Net P&L:</b> <span style="color:{color}; font-weight:bold;">{RUPEE}{net_pnl}</span>
                </div>
            """, unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True)

        with c1:
            render_bt_summary(norm_bt, "Normal Trend Strategy")
        with c2:
            render_bt_summary(rev_bt, "Reversal Contra Strategy")

def render_trade_table(trade_dict, title):
    st.markdown(f"### {title}")
    trades = list(trade_dict.values())
    if not trades:
        st.info("Koi active signal nahi mila.")
        return
    df = pd.DataFrame(trades)[["Time", "Symbol", "Type", "Qty", "Entry", "SL", "Exit", "Status", "GrossPnL", "NetPnL"]]
    st.dataframe(df, use_container_width=True)

with tab2:
    st.markdown("#### 🟢 Live Normal Strategy Terminal")
    render_trade_table(st.session_state.normal_trades, "Live Normal Strategy Signals")

with tab3:
    st.markdown("#### 🔴 Live Reversal Strategy Terminal")
    render_trade_table(st.session_state.reversal_trades, "Live Reversal Strategy Signals")
