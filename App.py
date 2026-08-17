import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG & STYLES
# -----------------------------------------------------------------------------
st.set_page_config(page_title="EMA Live Terminal & Backtest", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 2.5rem !important; padding-bottom: 0rem !important; padding-left: 1rem !important; padding-right: 1rem !important; }
    header[data-testid="stHeader"] { background: transparent; }
    .top-pnl-card {
        background: linear-gradient(135deg, #1e2530 0%, #161b22 100%);
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 15px;
        color: #ffffff;
    }
    .metric-val-green { color: #4CAF50; font-weight: bold; font-size: 18px; }
    .metric-val-red { color: #FF5252; font-weight: bold; font-size: 18px; }
    </style>
""", unsafe_allow_html=True)

RUPEE = "&#8377;"

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

HISTORY_FILE = "strategy_history_db.csv"
HISTORY_COLUMNS = [
    "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "StrategyMode", "Type", 
    "Qty", "EntryPrice", "ExitPrice", "SL", "Status", "GrossPnL", "Charges", "NetPnL"
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
# SIDEBAR CONTROL
# -----------------------------------------------------------------------------
if "watchlist" not in st.session_state:
    st.session_state.watchlist = DEFAULT_STOCKS.copy()

with st.sidebar:
    st.header("🔍 Dynamic Share Selection")
    
    new_stock = st.text_input("Add Custom NSE Ticker (e.g. ZOMATO):", "").strip().upper()
    if st.button("➕ Add Share to Watchlist"):
        if new_stock:
            formatted_symbol = new_stock if new_stock.endswith(".NS") else f"{new_stock}.NS"
            if formatted_symbol not in st.session_state.watchlist:
                st.session_state.watchlist.append(formatted_symbol)
                st.success(f"{formatted_symbol} added!")
                st.rerun()

    SELECTED_STOCKS = st.multiselect(
        "Active Watchlist (Max 10):",
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

    st.subheader("💰 Execution & Margin Settings")
    TRADE_VALUE = st.number_input("Trade Capital per Stock (Rs)", value=3000, step=500)
    LEVERAGE = st.number_input("Intraday Leverage Multiplier (e.g. 5x)", value=5, min_value=1, max_value=20, step=1)
    TIMEFRAME_MINS = st.selectbox("Candle Timeframe (Minutes)", [5, 15, 30, 60], index=1)
    
    st.markdown("---")
    AUTO_REFRESH = st.checkbox("🔄 Auto-Refresh Live P&L (15 sec)", value=True)

    if st.button("Clear Session & Logs"):
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
# REAL-TIME SIGNAL & LIVE PRICE ENGINE
# -----------------------------------------------------------------------------
@st.cache_data(ttl=10, show_spinner=False)
def fetch_market_data(stocks_list, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="5d", interval=tf_str, group_by="ticker", threads=True, progress=False)
        return data
    except Exception:
        return {}

def process_signals():
    data = fetch_market_data(SELECTED_STOCKS, TIMEFRAME_MINS)
    now_dt = datetime.now(ZoneInfo("Asia/Kolkata"))
    today_str = now_dt.strftime("%Y-%m-%d")
    current_time_str = now_dt.strftime("%H:%M:%S")

    effective_buying_power = TRADE_VALUE * LEVERAGE

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
            candle_time_str = timestamps[i].strftime("%H:%M")

            if candle_key not in st.session_state.processed_keys:
                st.session_state.processed_keys.add(candle_key)

                fast_curr, slow_curr = fast_ema[i], slow_ema[i]
                fast_prev, slow_prev = fast_ema[i-1], slow_ema[i-1]
                close_p, curr_atr = closes[i], atr[i]

                # STRICT CROSSOVER CONDITIONS
                norm_signal = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
                rev_signal = (fast_prev >= slow_prev) and (fast_curr < slow_curr)

                # 1. Normal Long Trade Entry
                if norm_signal and symbol not in [t["SymbolRaw"] for t in st.session_state.normal_trades.values() if t["Status"] == "LIVE"]:
                    qty = max(1, int(effective_buying_power / close_p))
                    sl_p = close_p - (ATR_MULT * curr_atr) if USE_ATR_STOP and not np.isnan(curr_atr) else close_p * 0.95
                    st.session_state.normal_trades[f"NORM_{candle_key}"] = {
                        "SymbolRaw": symbol, "Symbol": symbol.replace(".NS", ""), 
                        "EntryTime": candle_time_str, "ExitTime": "-",
                        "Type": "BUY", "Qty": qty, "EntryPrice": round(close_p, 2), 
                        "CurrentPrice": round(close_p, 2), "ExitPrice": "-", "SL": round(sl_p, 2),
                        "Status": "LIVE", "GrossPnL": 0.0, "Charges": 0.0, "NetPnL": 0.0, "Mode": "Normal"
                    }

                # 2. Reversal Short Trade Entry
                if rev_signal and symbol not in [t["SymbolRaw"] for t in st.session_state.reversal_trades.values() if t["Status"] == "LIVE"]:
                    qty = max(1, int(effective_buying_power / close_p))
                    sl_p = close_p + (ATR_MULT * curr_atr) if USE_ATR_STOP and not np.isnan(curr_atr) else close_p * 1.05
                    st.session_state.reversal_trades[f"REV_{candle_key}"] = {
                        "SymbolRaw": symbol, "Symbol": symbol.replace(".NS", ""), 
                        "EntryTime": candle_time_str, "ExitTime": "-",
                        "Type": "SELL", "Qty": qty, "EntryPrice": round(close_p, 2), 
                        "CurrentPrice": round(close_p, 2), "ExitPrice": "-", "SL": round(sl_p, 2),
                        "Status": "LIVE", "GrossPnL": 0.0, "Charges": 0.0, "NetPnL": 0.0, "Mode": "Reversal"
                    }

            # Live SL and P&L Monitor
            for trade_dict in [st.session_state.normal_trades, st.session_state.reversal_trades]:
                for k, t in list(trade_dict.items()):
                    if t["SymbolRaw"] == symbol and t["Status"] == "LIVE":
                        curr_close = closes[-1]
                        t["CurrentPrice"] = round(curr_close, 2)
                        is_long = t["Type"] == "BUY"

                        gross = (curr_close - t["EntryPrice"]) * t["Qty"] if is_long else (t["EntryPrice"] - curr_close) * t["Qty"]
                        chg = estimate_charges(t["EntryPrice"], curr_close, t["Qty"])
                        t["GrossPnL"] = round(gross, 2)
                        t["Charges"] = chg
                        t["NetPnL"] = round(gross - chg, 2)

                        hit_sl = (is_long and curr_close <= t["SL"]) or (not is_long and curr_close >= t["SL"])
                        if hit_sl:
                            t["Status"] = "SL HIT (CLOSED)"
                            t["ExitTime"] = current_time_str
                            t["ExitPrice"] = round(curr_close, 2)
                            append_db({
                                "Sr": len(load_db()) + 1, "Date": today_str, 
                                "EntryTime": t["EntryTime"], "ExitTime": t["ExitTime"], 
                                "Symbol": t["Symbol"], "StrategyMode": t["Mode"], "Type": t["Type"], 
                                "Qty": t["Qty"], "EntryPrice": t["EntryPrice"], "ExitPrice": t["ExitPrice"], 
                                "SL": t["SL"], "Status": t["Status"], "GrossPnL": t["GrossPnL"], 
                                "Charges": t["Charges"], "NetPnL": t["NetPnL"]
                            })
        except Exception:
            continue

# -----------------------------------------------------------------------------
# ACCURATE DUAL BACKTEST ENGINE (60 DAYS WITH SL CHECKING)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def run_60d_dual_backtest(stocks_list, fast_len, slow_len, atr_mult, use_atr, trade_val, leverage, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="60d", interval=tf_str, group_by="ticker", threads=True, progress=False)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    norm_list, rev_list = [], []
    buying_power = trade_val * leverage

    for symbol in stocks_list:
        try:
            df = data[symbol].dropna(how="all") if len(stocks_list) > 1 else data
            if df is None or len(df) < slow_len:
                continue

            df = df.copy()
            df["FastEMA"] = calculate_ema(df["Close"], fast_len)
            df["SlowEMA"] = calculate_ema(df["Close"], slow_len)
            df["ATR"] = calculate_atr(df, 14)

            closes, highs, lows = df["Close"].values, df["High"].values, df["Low"].values
            fast_ema, slow_ema, atr = df["FastEMA"].values, df["SlowEMA"].values, df["ATR"].values
            timestamps = df.index

            i = slow_len
            while i < len(df) - 1:
                fast_curr, slow_curr = fast_ema[i], slow_ema[i]
                fast_prev, slow_prev = fast_ema[i-1], slow_ema[i-1]
                entry_p, curr_atr = closes[i], atr[i]

                # 1. Long Normal Strategy Backtest
                if fast_prev <= slow_prev and fast_curr > slow_curr:
                    qty = max(1, int(buying_power / entry_p))
                    sl_p = entry_p - (atr_mult * curr_atr) if use_atr and not np.isnan(curr_atr) else entry_p * 0.95
                    
                    exit_p = closes[-1]
                    t_exit = timestamps[-1].strftime("%H:%M")
                    exit_idx = len(df) - 1

                    # Look forward to find exact SL hit or reverse crossover
                    for j in range(i + 1, len(df)):
                        if lows[j] <= sl_p:
                            exit_p = sl_p
                            t_exit = timestamps[j].strftime("%H:%M")
                            exit_idx = j
                            break
                        elif fast_ema[j] < slow_ema[j]: # Opposite crossover exit
                            exit_p = closes[j]
                            t_exit = timestamps[j].strftime("%H:%M")
                            exit_idx = j
                            break

                    gross = round((exit_p - entry_p) * qty, 2)
                    chg = estimate_charges(entry_p, exit_p, qty)
                    norm_list.append({
                        "Date": timestamps[i].strftime("%Y-%m-%d"), 
                        "EntryTime": timestamps[i].strftime("%H:%M"), "ExitTime": t_exit,
                        "Symbol": symbol.replace(".NS",""), "Type": "BUY", "Qty": qty, 
                        "EntryPrice": round(entry_p, 2), "ExitPrice": round(exit_p, 2), 
                        "GrossPnL": gross, "Charges": chg, "NetPnL": round(gross - chg, 2)
                    })
                    i = exit_idx + 1
                    continue

                # 2. Short Reversal Strategy Backtest
                if fast_prev >= slow_prev and fast_curr < slow_curr:
                    qty = max(1, int(buying_power / entry_p))
                    sl_p = entry_p + (atr_mult * curr_atr) if use_atr and not np.isnan(curr_atr) else entry_p * 1.05
                    
                    exit_p = closes[-1]
                    t_exit = timestamps[-1].strftime("%H:%M")
                    exit_idx = len(df) - 1

                    for j in range(i + 1, len(df)):
                        if highs[j] >= sl_p:
                            exit_p = sl_p
                            t_exit = timestamps[j].strftime("%H:%M")
                            exit_idx = j
                            break
                        elif fast_ema[j] > slow_ema[j]:
                            exit_p = closes[j]
                            t_exit = timestamps[j].strftime("%H:%M")
                            exit_idx = j
                            break

                    gross = round((entry_p - exit_p) * qty, 2)
                    chg = estimate_charges(entry_p, exit_p, qty)
                    rev_list.append({
                        "Date": timestamps[i].strftime("%Y-%m-%d"), 
                        "EntryTime": timestamps[i].strftime("%H:%M"), "ExitTime": t_exit,
                        "Symbol": symbol.replace(".NS",""), "Type": "SELL", "Qty": qty, 
                        "EntryPrice": round(entry_p, 2), "ExitPrice": round(exit_p, 2), 
                        "GrossPnL": gross, "Charges": chg, "NetPnL": round(gross - chg, 2)
                    })
                    i = exit_idx + 1
                    continue

                i += 1

        except Exception:
            continue

    df_norm = pd.DataFrame(norm_list)
    df_rev = pd.DataFrame(rev_list)
    
    if not df_norm.empty:
        df_norm.insert(0, "Sr", range(1, len(df_norm) + 1))
    if not df_rev.empty:
        df_rev.insert(0, "Sr", range(1, len(df_rev) + 1))

    return df_norm, df_rev

# -----------------------------------------------------------------------------
# SUMMARY CARDS & UI RENDERERS
# -----------------------------------------------------------------------------
def render_top_pnl_summary(trades_dict, title):
    st.markdown(f"### {title}")
    trades = list(trades_dict.values())
    
    total_trades = len(trades)
    tot_gross = sum([t["GrossPnL"] for t in trades])
    tot_charges = sum([t["Charges"] for t in trades])
    tot_net = round(tot_gross - tot_charges, 2)
    net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"
    gross_class = "metric-val-green" if tot_gross >= 0 else "metric-val-red"

    st.markdown(f"""
        <div class="top-pnl-card">
            <div style="display: flex; justify-content: space-around; text-align: center;">
                <div>
                    <span style="font-size: 12px; color: #8b949e;">TOTAL TRADES</span><br>
                    <span style="font-size: 18px; font-weight: bold;">{total_trades}</span>
                </div>
                <div>
                    <span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br>
                    <span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span>
                </div>
                <div>
                    <span style="font-size: 12px; color: #8b949e;">TOTAL CHARGES</span><br>
                    <span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_charges:.2f}</span>
                </div>
                <div>
                    <span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br>
                    <span class="{net_class}">{RUPEE}{tot_net:.2f}</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if not trades:
        st.info("Koi active live trade nahi mila.")
        return
    
    df = pd.DataFrame(trades)
    df.insert(0, "Sr", range(1, len(df) + 1))
    
    col_order = [
        "Sr", "EntryTime", "ExitTime", "Symbol", "Type", "Qty", 
        "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status", 
        "GrossPnL", "Charges", "NetPnL"
    ]
    st.dataframe(df[col_order], use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# APP TABS ROUTING
# -----------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "🟢 Tab 1: Live Normal Strategy",
    "🔴 Tab 2: Live Reversal Strategy",
    "📊 Tab 3: Backtest & History Database"
])

process_signals()

with tab1:
    render_top_pnl_summary(st.session_state.normal_trades, "🟢 Live Normal Strategy (Top P&L Summary)")

with tab2:
    render_top_pnl_summary(st.session_state.reversal_trades, "🔴 Live Reversal Strategy (Top P&L Summary)")

with tab3:
    st.markdown("### 📊 Dual Backtest Engine & Database Logs")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        run_btn = st.button("▶️ Run 60-Day Backtest", type="primary")

    if run_btn:
        with st.spinner("Selected stocks par 60-day historical data calculate ho raha hai..."):
            norm_bt, rev_bt = run_60d_dual_backtest(
                SELECTED_STOCKS, FAST_MA_LEN, SLOW_MA_LEN, 
                ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, TIMEFRAME_MINS
            )
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
            gross_pnl = round(df["GrossPnL"].sum(), 2)
            charges = round(df["Charges"].sum(), 2)
            net_pnl = round(df["NetPnL"].sum(), 2)
            net_class = "metric-val-green" if net_pnl >= 0 else "metric-val-red"

            bt_col_order = [
                "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type", 
                "Qty", "EntryPrice", "ExitPrice", "GrossPnL", "Charges", "NetPnL"
            ]

            st.markdown(f"#### {name}")
            st.markdown(f"""
                <div class="top-pnl-card">
                    <b>Total Trades:</b> {tot} | <b>Win Rate:</b> {wr}%<br>
                    <b>Gross P&L:</b> {RUPEE}{gross_pnl} | <b>Total Charges:</b> <span style="color:#e3b341;">{RUPEE}{charges}</span><br>
                    <b>Net P&L:</b> <span class="{net_class}">{RUPEE}{net_pnl}</span>
                </div>
            """, unsafe_allow_html=True)
            st.dataframe(df[bt_col_order], use_container_width=True, hide_index=True)

        with c1:
            render_bt_summary(norm_bt, "Normal Trend Strategy")
        with c2:
            render_bt_summary(rev_bt, "Reversal Contra Strategy")

    st.markdown("---")
    st.markdown("### 🗄️ Closed Trades Database History")
    db_df = load_db()
    if not db_df.empty:
        st.dataframe(db_df, use_container_width=True, hide_index=True)
    else:
        st.info("Abhi tak koi closed trade database mein save nahi hua hai.")

if AUTO_REFRESH:
    time.sleep(15)
    st.rerun()
