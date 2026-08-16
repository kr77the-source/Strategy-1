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
st.set_page_config(page_title="Intraday Scanner (ATR based, Trailing SL)", layout="wide")

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
    .badge-trail  { background-color: #29B6F630; color: #29B6F6; }
    .badge-sqoff  { background-color: #90A4AE30; color: #CFD8DC; }
    .badge-buy    { background-color: #4CAF5030; color: #4CAF50; }
    .badge-sell   { background-color: #FF525230; color: #FF5252; }
    </style>
""", unsafe_allow_html=True)

RUPEE = "&#8377;"

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
# PERSISTENT STORAGE (CSV)
# -----------------------------------------------------------------------------
HISTORY_FILE = "trade_history.csv"
HISTORY_COLUMNS = [
    "Date", "Time", "Symbol", "Type", "Qty", "Entry", "SL", "Target",
    "Exit", "Status", "GrossPnL", "Charges", "NetPnL", "ATR"
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

    st.subheader("ATR-based SL / Target")
    st.caption("SL and Target scale with each stock's own recent volatility (14-period ATR on 5-min candles).")
    SL_ATR_MULT = st.number_input("SL = ATR x", value=1.0, step=0.1, format="%.1f")
    TARGET_ATR_MULT = st.number_input("Target = ATR x", value=2.0, step=0.1, format="%.1f")
    st.caption(f"Risk:Reward = 1 : {round(TARGET_ATR_MULT/SL_ATR_MULT, 2)}")

    st.subheader("Trailing SL / Target")
    TRAILING_ENABLED = st.checkbox("Enable trailing (let winners run)", value=True)
    st.caption(
        "ON: jab tak SL hit nahi hota, SL profit ki taraf trail karta rahega aur target bhi "
        "aage badhta rahega (koi fixed profit cap nahi). OFF: purana fixed SL/Target behavior."
    )

    st.subheader("Stock filter (avoid dead / illiquid stocks)")
    st.caption("NOTE: this is % of price PER 5-MIN CANDLE, not daily range â€” typical values are 0.1%-0.4%, not 1-2%.")
    MIN_ATR_PCT = st.number_input("Min 5-min ATR as % of price", value=0.20, step=0.05, format="%.2f") / 100
    st.caption("Stocks whose 5-min ATR is below this % of price are skipped for the day â€” they rarely move enough to hit target.")

    st.subheader("Overtrading control")
    ONE_TRADE_PER_STOCK_PER_DAY = st.checkbox("Max 1 trade per stock per day", value=True)

    if st.button("Reset TODAY's live signals (keeps history file)"):
        st.session_state.trade_log = {}
        st.session_state.processed_keys = set()
        st.session_state.traded_today = set()

    if st.button("Delete ALL saved history (irreversible)"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.session_state.trade_log = {}
        st.session_state.processed_keys = set()
        st.session_state.traded_today = set()

CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES

if "trade_log" not in st.session_state:
    st.session_state.trade_log = {}
if "processed_keys" not in st.session_state:
    st.session_state.processed_keys = set()
if "traded_today" not in st.session_state:
    st.session_state.traded_today = set()


def is_market_open(now_dt):
    return time(9, 15) <= now_dt.time() <= time(15, 30)


def calculate_vwap(df):
    v = df["Volume"].values
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * v).cumsum() / np.maximum(v.cumsum(), 1)


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
# SHARED TRADE SIMULATION (used by both live scanner and backtest so the
# trailing logic behaves identically in both places).
#
# When trailing_enabled=True:
#   - SL only ever moves in the trade's favour (never loosens).
#   - "Target" is not a hard exit â€” it keeps extending as price makes new
#     favourable extremes. The trade only closes on trailing-SL hit or EOD.
#   - If the SL is hit AFTER it has trailed past entry (i.e. exit price is
#     already in profit), status is TRAIL instead of SL, so you can tell a
#     locked-in profit apart from a genuine loss.
# When trailing_enabled=False: original fixed SL / fixed Target behaviour.
# -----------------------------------------------------------------------------
def simulate_trade(highs, lows, closes, timestamps, start_idx, entry, is_long,
                    atr_at_entry, sl_atr_mult, target_atr_mult, trailing_enabled):
    sl = round(entry - atr_at_entry * sl_atr_mult, 2) if is_long else round(entry + atr_at_entry * sl_atr_mult, 2)
    target = round(entry + atr_at_entry * target_atr_mult, 2) if is_long else round(entry - atr_at_entry * target_atr_mult, 2)
    peak = entry

    status, exit_price, exit_idx = "LIVE", None, len(highs) - 1

    for j in range(start_idx, len(highs)):
        t_str = timestamps[j].strftime("%H:%M")

        if trailing_enabled:
            if is_long:
                peak = max(peak, highs[j])
                trail_sl = round(peak - atr_at_entry * sl_atr_mult, 2)
                sl = max(sl, trail_sl)
                target = round(peak + atr_at_entry * target_atr_mult, 2)
            else:
                peak = min(peak, lows[j])
                trail_sl = round(peak + atr_at_entry * sl_atr_mult, 2)
                sl = min(sl, trail_sl)
                target = round(peak - atr_at_entry * target_atr_mult, 2)

        hit_sl = (is_long and lows[j] <= sl) or (not is_long and highs[j] >= sl)
        hit_target = False
        if not trailing_enabled:
            hit_target = (is_long and highs[j] >= target) or (not is_long and lows[j] <= target)

        if hit_target:
            status, exit_price, exit_idx = "TARGET", target, j
            break
        if hit_sl:
            if trailing_enabled and ((is_long and sl > entry) or (not is_long and sl < entry)):
                status = "TRAIL"
            else:
                status = "SL"
            exit_price, exit_idx = sl, j
            break
        if t_str >= "15:20":
            status, exit_price, exit_idx = "SQOFF", round(float(closes[j]), 2), j
            break
    else:
        exit_price, exit_idx = round(float(closes[-1]), 2), len(highs) - 1
        status = "LIVE"

    return status, exit_price, exit_idx, sl, target


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
    "TRAIL": ("TRAIL LOCKED", "badge-trail"),
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
            df["ATR"] = calculate_atr(df, 14)

            closes, highs, lows = df["Close"].values, df["High"].values, df["Low"].values
            ema20, vwap, atr = df["EMA20"].values, df["VWAP"].values, df["ATR"].values
            timestamps = df.index

            # --- Update LIVE trades (fully re-simulated each cycle â€” deterministic
            # since past candles never change, so this is safe and stateless) ---
            for key, trade in list(st.session_state.trade_log.items()):
                if trade["SymbolRaw"] != symbol or trade["Status"] != "LIVE":
                    continue

                entry_idx, is_long = trade["EntryIdx"], trade["IsLong"]

                status, exit_price, exit_idx, final_sl, final_target = simulate_trade(
                    highs, lows, closes, timestamps, entry_idx + 1,
                    trade["Entry"], is_long, trade["ATRVal"],
                    SL_ATR_MULT, TARGET_ATR_MULT, TRAILING_ENABLED,
                )

                trade["SL"], trade["Target"] = final_sl, final_target
                trade["CMP/Exit"] = exit_price
                trade["Status"] = status

                gross = (
                    round((exit_price - trade["Entry"]) * trade["Qty"], 2) if is_long
                    else round((trade["Entry"] - exit_price) * trade["Qty"], 2)
                )
                trade["Gross P&L"] = gross

                if status != "LIVE":
                    est_tax = estimate_charges(trade["Entry"], exit_price, trade["Qty"])
                    net = round(gross - est_tax, 2)
                    trade["Tax"] = est_tax
                    trade["Net P&L"] = net
                    append_history({
                        "Date": today_str, "Time": trade["Time"], "Symbol": trade["Symbol"],
                        "Type": trade["TypeLabel"], "Qty": trade["Qty"], "Entry": trade["Entry"],
                        "SL": final_sl, "Target": final_target, "Exit": exit_price,
                        "Status": status, "GrossPnL": gross, "Charges": est_tax,
                        "NetPnL": net, "ATR": trade.get("ATRVal", None),
                    })
                else:
                    trade["Tax"], trade["Net P&L"] = None, None

            # --- Detect NEW signals ---
            for i in range(20, len(df)):
                t_str = timestamps[i].strftime("%H:%M")
                if t_str >= "15:15":
                    break

                candle_key = f"{symbol}_{timestamps[i].isoformat()}"
                if candle_key in st.session_state.processed_keys:
                    continue
                st.session_state.processed_keys.add(candle_key)

                curr_atr = atr[i]
                if np.isnan(curr_atr) or curr_atr <= 0:
                    continue

                curr_close, curr_high, curr_low = closes[i], highs[i], lows[i]
                curr_ema, curr_vwap = ema20[i], vwap[i]

                if curr_atr < curr_close * MIN_ATR_PCT:
                    continue
                if ONE_TRADE_PER_STOCK_PER_DAY and (symbol, today_str) in st.session_state.traded_today:
                    continue

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
                sl_init = round(entry - curr_atr * SL_ATR_MULT, 2) if is_long else round(entry + curr_atr * SL_ATR_MULT, 2)
                target_init = round(entry + curr_atr * TARGET_ATR_MULT, 2) if is_long else round(entry - curr_atr * TARGET_ATR_MULT, 2)

                st.session_state.trade_log[candle_key] = {
                    "SymbolRaw": symbol, "EntryIdx": i, "IsLong": is_long,
                    "Time": t_str, "Symbol": symbol.replace(".NS", ""),
                    "TypeLabel": "BUY" if is_long else "SELL",
                    "Qty": qty, "Entry": entry, "SL": sl_init, "Target": target_init,
                    "Status": "LIVE", "CMP/Exit": entry,
                    "Gross P&L": 0.0, "Tax": None, "Net P&L": None,
                    "ATRVal": round(float(curr_atr), 2),
                }
                if ONE_TRADE_PER_STOCK_PER_DAY:
                    st.session_state.traded_today.add((symbol, today_str))
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

    today_targets = len(today_df[today_df["Status"].isin(["TARGET", "TRAIL"])]) if not today_df.empty else 0
    today_sl = len(today_df[today_df["Status"] == "SL"]) if not today_df.empty else 0
    today_net = round(today_df["NetPnL"].sum(), 2) if not today_df.empty else 0.0
    today_gross = round(today_df["GrossPnL"].sum(), 2) if not today_df.empty else 0.0
    today_charges = round(today_df["Charges"].sum(), 2) if not today_df.empty else 0.0

    alltime_targets = len(history_df[history_df["Status"].isin(["TARGET", "TRAIL"])]) if not history_df.empty else 0
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
            <b>TODAY</b> &mdash; Trades: {len(today_df)} | Profitable exits (Target+Trail): {today_targets} | SL: {today_sl}<br>
            Gross: <span style="color:{net_color_today};">{RUPEE}{today_gross}</span> |
            Charges: <span style="color:#FF9800;">{RUPEE}{today_charges}</span> |
            Net: <span style="color:{net_color_today}; font-weight:bold;">{RUPEE}{today_net}</span><br><br>
            <b>ALL-TIME (saved history)</b> &mdash; Trades: {alltime_trades} | Profitable exits: {alltime_targets} | SL: {alltime_sl} |
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
                "Time": t["Time"], "Symbol": t["Symbol"], "Type": badge(t["TypeLabel"], type_cls),
                "Qty": t["Qty"], "Entry": t["Entry"], "SL": t["SL"], "Target": t["Target"],
                "ATR": t.get("ATRVal", "-"),
                "CMP/Exit": t["CMP/Exit"], "Status": badge(label, cls),
                "Gross P&L": t["Gross P&L"], "Net P&L": t["Net P&L"] if t["Net P&L"] is not None else "-",
            })
        display_df = pd.DataFrame(rows)
        st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Market open hone par live signals scan ho kar auto-appear honge.")

    with st.expander("Full saved trade history (all days)"):
        if not history_df.empty:
            st.dataframe(history_df.iloc[::-1], use_container_width=True)
            st.download_button("Download full history CSV", data=history_df.to_csv(index=False),
                                file_name="trade_history.csv", mime="text/csv")
        else:
            st.caption("Abhi koi closed trade save nahi hui hai.")


# -----------------------------------------------------------------------------
# BACKTEST: last 60 days, same trailing / fixed logic as live, via simulate_trade().
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def run_backtest(sl_atr_mult, target_atr_mult, min_atr_pct, one_per_day, trailing_enabled, capital_per_stock, symbols):
    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period="60d", interval="5m", group_by="ticker",
            threads=True, progress=False, auto_adjust=False,
        )
    except Exception:
        return pd.DataFrame()

    all_trades = []

    for symbol in symbols:
        try:
            df = data[symbol].dropna(how="all") if len(symbols) > 1 else data
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df = df.copy()
        df["DateOnly"] = df.index.date

        for day, day_df in df.groupby("DateOnly"):
            day_df = day_df.copy()
            if len(day_df) < 20:
                continue

            day_df["EMA20"] = day_df["Close"].ewm(span=20, adjust=False).mean()
            day_df["VWAP"] = calculate_vwap(day_df)
            day_df["ATR"] = calculate_atr(day_df, 14)

            closes, highs, lows = day_df["Close"].values, day_df["High"].values, day_df["Low"].values
            ema20, vwap, atr = day_df["EMA20"].values, day_df["VWAP"].values, day_df["ATR"].values
            timestamps = day_df.index

            traded_this_day = False
            i = 20
            while i < len(day_df):
                t_str = timestamps[i].strftime("%H:%M")
                if t_str >= "15:15":
                    break
                if one_per_day and traded_this_day:
                    break

                curr_atr = atr[i]
                if np.isnan(curr_atr) or curr_atr <= 0:
                    i += 1
                    continue

                curr_close, curr_high, curr_low = closes[i], highs[i], lows[i]
                curr_ema, curr_vwap = ema20[i], vwap[i]

                if curr_atr < curr_close * min_atr_pct:
                    i += 1
                    continue

                bullish = curr_ema > curr_vwap
                long_pullback = bullish and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)
                bearish = curr_ema < curr_vwap
                short_pullback = bearish and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if not (long_pullback or short_pullback):
                    i += 1
                    continue

                is_long = long_pullback
                entry = round(float(curr_close), 2)
                qty = max(1, int(capital_per_stock / entry))

                status, exit_price, exit_j, final_sl, final_target = simulate_trade(
                    highs, lows, closes, timestamps, i + 1, entry, is_long,
                    curr_atr, sl_atr_mult, target_atr_mult, trailing_enabled,
                )
                if status == "LIVE":  # ran out of candles for the day without closing â€” treat as sq-off at last close
                    status, exit_price = "SQOFF", round(float(closes[-1]), 2)

                gross = round((exit_price - entry) * qty, 2) if is_long else round((entry - exit_price) * qty, 2)
                charges = estimate_charges(entry, exit_price, qty)
                net = round(gross - charges, 2)

                all_trades.append({
                    "Date": str(day), "Time": t_str, "Symbol": symbol.replace(".NS", ""),
                    "Type": "BUY" if is_long else "SELL", "Qty": qty, "Entry": entry,
                    "SL": final_sl, "Target": final_target, "Exit": exit_price, "Status": status,
                    "GrossPnL": gross, "Charges": charges, "NetPnL": net, "ATR": round(float(curr_atr), 2),
                })

                traded_this_day = True
                i = exit_j + 1

    return pd.DataFrame(all_trades)


def render_backtest_tab():
    st.markdown("### Backtest (last 60 days)")
    st.caption(
        "SL/Target ATR-based hain. Trailing ON hai to profit lock hote hue winners aage chalenge; "
        "OFF hai to fixed SL/Target wapas aa jaayega."
    )

    if st.button("Run Backtest"):
        with st.spinner("Backtest chal raha hai, thoda time lagega..."):
            bt_df = run_backtest(
                SL_ATR_MULT, TARGET_ATR_MULT, MIN_ATR_PCT,
                ONE_TRADE_PER_STOCK_PER_DAY, TRAILING_ENABLED, CAPITAL_PER_STOCK, UNDER_300_WATCHLIST
            )
        st.session_state.backtest_result = bt_df

    bt_df = st.session_state.get("backtest_result")

    if bt_df is None:
        st.info("Button dabao backtest chalane ke liye.")
        return

    if bt_df.empty:
        st.warning("Koi trade nahi mila is period me in settings ke saath â€” filter shayad zyada strict hai.")
        return

    total_trades = len(bt_df)
    targets = len(bt_df[bt_df["Status"] == "TARGET"])
    trails = len(bt_df[bt_df["Status"] == "TRAIL"])
    profitable = targets + trails
    sl_hits = len(bt_df[bt_df["Status"] == "SL"])
    sqoff = len(bt_df[bt_df["Status"] == "SQOFF"])
    win_rate = round((profitable / total_trades) * 100, 1) if total_trades else 0.0
    sqoff_rate = round((sqoff / total_trades) * 100, 1) if total_trades else 0.0
    total_gross = round(bt_df["GrossPnL"].sum(), 2)
    total_charges = round(bt_df["Charges"].sum(), 2)
    total_net = round(bt_df["NetPnL"].sum(), 2)
    avg_net_per_trade = round(total_net / total_trades, 2) if total_trades else 0.0

    net_color = "#4CAF50" if total_net >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="pnl-card">
            <b>Total Trades:</b> {total_trades} | <b>Profitable (Target+Trail):</b> {profitable} ({win_rate}%)
            &nbsp;[Target: {targets}, Trail-locked: {trails}] |
            <b>SL Hit:</b> {sl_hits} | <b>Auto Sq-off:</b> {sqoff} ({sqoff_rate}%)<br><br>
            <b>Gross P&L:</b> {RUPEE}{total_gross} |
            <b>Total Charges:</b> {RUPEE}{total_charges} |
            <b>Net P&L:</b> <span style="color:{net_color}; font-weight:bold;">{RUPEE}{total_net}</span><br>
            <b>Avg Net P&L / trade:</b> {RUPEE}{avg_net_per_trade}
        </div>
    """, unsafe_allow_html=True)

    if sqoff_rate > 50:
        st.warning(
            f"{sqoff_rate}% trades sirf auto sq-off ho rahe hain (na SL na trail-exit). "
            "MIN_ATR_PCT filter dheela karo (kam karo) ya SL_ATR_MULT kam karo taaki jaldi trail shuru ho."
        )

    daily = bt_df.groupby("Date")["NetPnL"].sum().reset_index()
    daily["CumulativeNetPnL"] = daily["NetPnL"].cumsum()

    st.markdown("#### Day-wise P&L")
    st.dataframe(daily, use_container_width=True)

    st.markdown("#### Equity Curve (cumulative Net P&L)")
    st.line_chart(daily.set_index("Date")["CumulativeNetPnL"])

    st.markdown("#### Per-stock performance")
    per_stock = bt_df.groupby("Symbol").agg(
        Trades=("NetPnL", "count"),
        Profitable=("Status", lambda s: s.isin(["TARGET", "TRAIL"]).sum()),
        SLHits=("Status", lambda s: (s == "SL").sum()),
        NetPnL=("NetPnL", "sum"),
    ).reset_index().sort_values("NetPnL", ascending=False)
    st.dataframe(per_stock, use_container_width=True)

    with st.expander("All backtest trades"):
        st.dataframe(bt_df.iloc[::-1], use_container_width=True)
        st.download_button("Download backtest CSV", data=bt_df.to_csv(index=False),
                            file_name="backtest_60days.csv", mime="text/csv")


# -----------------------------------------------------------------------------
# MAIN LAYOUT
# -----------------------------------------------------------------------------
st.markdown("### INTRADAY SCANNER (ATR based, Trailing SL/Target)")
tab_live, tab_backtest = st.tabs(["Live Dashboard", "Backtest"])

with tab_live:
    render_dashboard()

with tab_backtest:
    render_backtest_tab()
