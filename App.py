import os
import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# PAGE CONFIG & STYLES - Dashboard Layout
# =============================================================================
st.set_page_config(page_title="EMA Intraday Live Terminal & Backtest", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 2rem !important; padding-bottom: 0rem !important; padding-left: 1rem !important; padding-right: 1rem !important; }
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

IST = ZoneInfo("Asia/Kolkata")
RUPEE = "&#8377;"

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

HISTORY_FILE = "strategy_history_db.csv"
HISTORY_COLUMNS = [
    "TradeID", "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "StrategyMode",
    "Type", "Qty", "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status",
    "GrossPnL", "Charges", "NetPnL", "EntryReason", "ExitReason"
]

# =============================================================================
# STORAGE ENGINE
# =============================================================================
def load_db():
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE)
            for col in HISTORY_COLUMNS:
                if col not in df.columns:
                    df[col] = "-"
            return df[HISTORY_COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=HISTORY_COLUMNS)

def save_db(df):
    df.to_csv(HISTORY_FILE, index=False)

def upsert_trade_to_db(trade_data: dict):
    df = load_db()
    tid = str(trade_data["TradeID"])
    if not df.empty and tid in df["TradeID"].astype(str).values:
        idx = df.index[df["TradeID"].astype(str) == tid][0]
        for key, val in trade_data.items():
            if key in df.columns:
                df.at[idx, key] = val
    else:
        trade_data = {c: trade_data.get(c, "-") for c in HISTORY_COLUMNS}
        trade_data["Sr"] = len(df) + 1
        df = pd.concat([df, pd.DataFrame([trade_data])], ignore_index=True)
    save_db(df)

# =============================================================================
# INDICATORS & STRATEGY ENGINE
# =============================================================================
def calculate_ema(series, period):
    return series.ewm(span=int(period), adjust=False).mean()

def calculate_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()

def add_indicators(df, fast_len, slow_len, atr_len):
    out = df.copy()
    out["FastEMA"] = calculate_ema(out["Close"], fast_len)
    out["SlowEMA"] = calculate_ema(out["Close"], slow_len)
    out["ATR"] = calculate_atr(out, atr_len)
    return out

def signal_at(df, i):
    if i <= 0:
        return False, False
    fp, sp = float(df["FastEMA"].iloc[i - 1]), float(df["SlowEMA"].iloc[i - 1])
    fc, sc = float(df["FastEMA"].iloc[i]), float(df["SlowEMA"].iloc[i])
    if any(np.isnan(x) for x in (fp, sp, fc, sc)):
        return False, False
    return (fp <= sp and fc > sc), (fp >= sp and fc < sc)

# =============================================================================
# CHARGES & SLIPPAGE
# =============================================================================
def estimate_charges(entry_price, exit_price, qty):
    buy_turnover = float(entry_price) * int(qty)
    sell_turnover = float(exit_price) * int(qty)
    total_turnover = buy_turnover + sell_turnover
    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00025
    exchange_charges = total_turnover * 0.0000297
    gst = (brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_charges = total_turnover * 0.000001
    return round(brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)

def apply_slippage(price, side, bps=5.0):
    p = float(price)
    b = float(bps) / 10000.0
    return p * (1 + b) if side == "BUY" else p * (1 - b)

# =============================================================================
# DATA FETCHING ENGINE (REAL YFINANCE DATA)
# =============================================================================
@st.cache_data(ttl=10, show_spinner=False)
def fetch_market_data(stocks_list, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(
            tickers=" ".join(stocks_list),
            period="5d",
            interval=tf_str,
            group_by="ticker",
            threads=True,
            progress=False
        )
        return data
    except Exception as e:
        st.error(f"Market Data Fetch Error: {e}")
        return {}

def market_open_now(now):
    t = now.time()
    return dt_time(9, 15) <= t < dt_time(15, 30) and now.weekday() < 5

def should_squareoff(now):
    return now.time() >= dt_time(15, 25)

# =============================================================================
# LIVE PROCESSOR ENGINE
# =============================================================================
def process_live(selected_stocks, tf_mins, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_capital, leverage, slippage_bps):
    now = datetime.now(IST)
    data = fetch_market_data(selected_stocks, tf_mins)
    if data is None or (isinstance(data, dict) and not data):
        return

    buying_power = float(trade_capital) * float(leverage)
    db = load_db()

    for symbol in selected_stocks:
        try:
            df = data[symbol].dropna(how="all") if len(selected_stocks) > 1 else data
            if df is None or len(df) < slow_len + 2:
                continue

            ind = add_indicators(df, fast_len, slow_len, atr_len)
            i = len(ind) - 1
            norm_signal, rev_signal = signal_at(ind, i)
            atr_val = float(ind["ATR"].iloc[i])
            ltp = float(ind["Close"].iloc[i])

            # Manage active positions
            active_trades = db[(db["Symbol"] == symbol.replace(".NS", "")) & (db["Status"] == "LIVE")]

            for _, row in active_trades.iterrows():
                mode = row["StrategyMode"]
                side = row["Type"]
                entry_p = float(row["EntryPrice"])
                qty = int(row["Qty"])
                sl_p = float(row["SL"])

                gross = (ltp - entry_p) * qty if side == "BUY" else (entry_p - ltp) * qty
                charges = estimate_charges(entry_p, ltp, qty)
                updated = dict(row)
                updated["CurrentPrice"] = round(ltp, 2)
                updated["GrossPnL"] = round(gross, 2)
                updated["Charges"] = round(charges, 2)
                updated["NetPnL"] = round(gross - charges, 2)

                hit_sl = (side == "BUY" and ltp <= sl_p) or (side == "SELL" and ltp >= sl_p)
                opposite_signal = (side == "BUY" and rev_signal) or (side == "SELL" and norm_signal)
                is_eod = should_squareoff(now)

                if hit_sl or opposite_signal or is_eod:
                    exit_p = apply_slippage(ltp, "SELL" if side == "BUY" else "BUY", slippage_bps)
                    gross_final = (exit_p - entry_p) * qty if side == "BUY" else (entry_p - exit_p) * qty
                    charges_final = estimate_charges(entry_p, exit_p, qty)

                    reason = "SL_HIT" if hit_sl else ("OPPOSITE_SIGNAL" if opposite_signal else "EOD_SQUAREOFF")
                    updated.update({
                        "ExitPrice": round(exit_p, 2),
                        "ExitTime": now.strftime("%H:%M:%S"),
                        "Status": f"CLOSED ({reason})",
                        "GrossPnL": round(gross_final, 2),
                        "Charges": charges_final,
                        "NetPnL": round(gross_final - charges_final, 2),
                        "ExitReason": reason
                    })
                upsert_trade_to_db(updated)

            # Process new signals
            if "processed_keys" not in st.session_state:
                st.session_state.processed_keys = set()

            candle_key = f"{symbol}_{ind.index[i].isoformat()}"

            if candle_key not in st.session_state.processed_keys:
                st.session_state.processed_keys.add(candle_key)
                symbol_clean = symbol.replace(".NS", "")

                if norm_signal and db[(db["Symbol"] == symbol_clean) & (db["StrategyMode"] == "Normal") & (db["Status"] == "LIVE")].empty:
                    entry_p = apply_slippage(ltp, "BUY", slippage_bps)
                    qty = max(1, int(buying_power / max(entry_p, 0.01)))
                    sl_p = entry_p - (atr_mult * atr_val) if use_atr and not np.isnan(atr_val) else entry_p * 0.95
                    
                    upsert_trade_to_db({
                        "TradeID": f"N_{now.strftime('%Y%m%d%H%M%S')}_{symbol_clean}",
                        "Date": now.strftime("%Y-%m-%d"),
                        "EntryTime": now.strftime("%H:%M:%S"),
                        "ExitTime": "-",
                        "Symbol": symbol_clean,
                        "StrategyMode": "Normal",
                        "Type": "BUY",
                        "Qty": qty,
                        "EntryPrice": round(entry_p, 2),
                        "CurrentPrice": round(entry_p, 2),
                        "ExitPrice": "-",
                        "SL": round(sl_p, 2),
                        "Status": "LIVE",
                        "GrossPnL": 0.0,
                        "Charges": 0.0,
                        "NetPnL": 0.0,
                        "EntryReason": "EMA_CROSSOVER_BUY",
                        "ExitReason": "-"
                    })

                if rev_signal and db[(db["Symbol"] == symbol_clean) & (db["StrategyMode"] == "Reversal") & (db["Status"] == "LIVE")].empty:
                    entry_p = apply_slippage(ltp, "SELL", slippage_bps)
                    qty = max(1, int(buying_power / max(entry_p, 0.01)))
                    sl_p = entry_p + (atr_mult * atr_val) if use_atr and not np.isnan(atr_val) else entry_p * 1.05
                    
                    upsert_trade_to_db({
                        "TradeID": f"R_{now.strftime('%Y%m%d%H%M%S')}_{symbol_clean}",
                        "Date": now.strftime("%Y-%m-%d"),
                        "EntryTime": now.strftime("%H:%M:%S"),
                        "ExitTime": "-",
                        "Symbol": symbol_clean,
                        "StrategyMode": "Reversal",
                        "Type": "SELL",
                        "Qty": qty,
                        "EntryPrice": round(entry_p, 2),
                        "CurrentPrice": round(entry_p, 2),
                        "ExitPrice": "-",
                        "SL": round(sl_p, 2),
                        "Status": "LIVE",
                        "GrossPnL": 0.0,
                        "Charges": 0.0,
                        "NetPnL": 0.0,
                        "EntryReason": "EMA_CROSSOVER_SELL",
                        "ExitReason": "-"
                    })

        except Exception:
            continue

# =============================================================================
# BACKTEST ENGINE (60 DAYS - STRICT INTRADAY NO OVERNIGHT)
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def run_60d_backtest(stocks_list, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_val, leverage, tf_mins, slippage_bps):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="60d", interval=tf_str, group_by="ticker", threads=True, progress=False)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    norm_list, rev_list = [], []
    buying_power = float(trade_val) * float(leverage)

    for symbol in stocks_list:
        try:
            df = data[symbol].dropna(how="all") if len(stocks_list) > 1 else data
            if df is None or len(df) < slow_len + 10:
                continue

            df = add_indicators(df, fast_len, slow_len, atr_len)

            for mode, side, out_list in [("Normal", "BUY", norm_list), ("Reversal", "SELL", rev_list)]:
                open_trade = None
                for i in range(slow_len + 1, len(df) - 1):
                    current_dt = df.index[i]
                    next_dt = df.index[i + 1]
                    c_time = current_dt.time()
                    
                    # Strictly detect last candle of current trading day
                    is_last_candle_of_day = (next_dt.date() != current_dt.date()) or (c_time >= dt_time(15, 15))

                    if open_trade is not None:
                        hi, lo, close = float(df["High"].iloc[i]), float(df["Low"].iloc[i]), float(df["Close"].iloc[i])
                        ts = current_dt
                        exit_price, reason = None, None

                        # 1. Check ATR Stop Loss
                        if side == "BUY" and use_atr and lo <= open_trade["SL"]:
                            exit_price, reason = open_trade["SL"], "ATR_SL"
                        elif side == "SELL" and use_atr and hi >= open_trade["SL"]:
                            exit_price, reason = open_trade["SL"], "ATR_SL"
                        
                        # 2. Strict Same-Day EOD Square-off
                        elif is_last_candle_of_day:
                            exit_price = apply_slippage(close, "SELL" if side == "BUY" else "BUY", slippage_bps)
                            reason = "EOD_SQUAREOFF"

                        # 3. Check Opposite Crossover Signal
                        else:
                            ns, rs = signal_at(df, i)
                            if (side == "BUY" and rs) or (side == "SELL" and ns):
                                exit_price = apply_slippage(float(df["Open"].iloc[i + 1]), "SELL" if side == "BUY" else "BUY", slippage_bps)
                                reason = "OPPOSITE_SIGNAL"
                                ts = df.index[i + 1]

                        # Process Trade Exit
                        if exit_price is not None:
                            entry, qty = open_trade["EntryPrice"], open_trade["Qty"]
                            gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                            chg = estimate_charges(entry, exit_price, qty)
                            out_list.append({
                                "Date": open_trade["Date"], 
                                "EntryTime": open_trade["EntryTime"], 
                                "ExitTime": ts.strftime("%H:%M"),
                                "Symbol": symbol.replace(".NS", ""), 
                                "Type": side, 
                                "Qty": qty,
                                "EntryPrice": round(entry, 2), 
                                "ExitPrice": round(exit_price, 2), 
                                "SL": round(open_trade["SL"], 2),
                                "GrossPnL": round(gross, 2), 
                                "Charges": chg, 
                                "NetPnL": round(gross - chg, 2), 
                                "ExitReason": reason
                            })
                            open_trade = None
                            continue

                    # Trigger New Intraday Entry (Strictly before 3:00 PM and not on last candle)
                    if c_time < dt_time(15, 0) and not is_last_candle_of_day:
                        ns, rs = signal_at(df, i)
                        trigger = ns if side == "BUY" else rs
                        if trigger and open_trade is None and i + 1 < len(df):
                            entry_raw = float(df["Open"].iloc[i + 1])
                            entry = apply_slippage(entry_raw, side, slippage_bps)
                            atr = float(df["ATR"].iloc[i])
                            sl = (entry - atr_mult * atr) if side == "BUY" else (entry + atr_mult * atr)
                            qty = max(1, int(buying_power / max(entry, 0.01)))
                            open_trade = {
                                "Date": df.index[i + 1].strftime("%Y-%m-%d"), 
                                "EntryTime": df.index[i + 1].strftime("%H:%M"), 
                                "EntryPrice": entry, 
                                "SL": sl, 
                                "Qty": qty
                            }

        except Exception:
            continue

    norm, rev = pd.DataFrame(norm_list), pd.DataFrame(rev_list)
    if not norm.empty: norm.insert(0, "Sr", range(1, len(norm) + 1))
    if not rev.empty: rev.insert(0, "Sr", range(1, len(rev) + 1))
    return norm, rev

# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================
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
    LEVERAGE = st.number_input("Intraday Margin Leverage (e.g. 5x)", value=5, min_value=1, max_value=20, step=1)
    TIMEFRAME_MINS = st.selectbox("Candle Timeframe (Minutes)", [5, 15, 30, 60], index=1)
    SLIPPAGE_BPS = st.number_input("Slippage (BPS)", value=5.0, step=1.0)

    st.markdown("---")
    AUTO_REFRESH = st.checkbox("🔄 Auto-Refresh Live P&L (15 sec)", value=True)

    if st.button("🗑️ Reset History DB"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.session_state.processed_keys = set()
        st.success("History database reset ho gaya!")
        st.rerun()

if not SELECTED_STOCKS:
    st.warning("⚠️ Kam se kam 1 share select karein.")
    st.stop()

# Run Live Signal Engine
process_live(SELECTED_STOCKS, TIMEFRAME_MINS, FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, SLIPPAGE_BPS)

# =============================================================================
# UI DISPLAY TABS
# =============================================================================
tab1, tab2, tab3 = st.tabs([
    "🟢 Live Normal Strategy",
    "🔴 Live Reversal Strategy",
    "📊 Backtest & Master DB"
])

def render_live_tab(strategy_mode, title):
    st.markdown(f"### {title}")
    db_df = load_db()
    mode_df = db_df[db_df["StrategyMode"] == strategy_mode] if not db_df.empty else pd.DataFrame()

    total_trades = len(mode_df)
    tot_gross = mode_df["GrossPnL"].astype(float).sum() if not mode_df.empty else 0.0
    tot_charges = mode_df["Charges"].astype(float).sum() if not mode_df.empty else 0.0
    tot_net = round(tot_gross - tot_charges, 2)

    net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"
    gross_class = "metric-val-green" if tot_gross >= 0 else "metric-val-red"

    st.markdown(f"""
        <div class="top-pnl-card">
            <div style="display: flex; justify-content: space-around; text-align: center;">
                <div><span style="font-size: 12px; color: #8b949e;">TRADES</span><br><span style="font-size: 18px; font-weight: bold;">{total_trades}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_charges:.2f}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if mode_df.empty:
        st.info("Koi active ya closed trade record nahi mila.")
        return

    col_order = ["Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type", "Qty", "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status", "GrossPnL", "Charges", "NetPnL"]
    st.markdown("#### 🟢 Active Positions")
    st.dataframe(mode_df[mode_df["Status"] == "LIVE"][col_order], use_container_width=True, hide_index=True)
    st.markdown("#### 🗄️ Closed Trades")
    st.dataframe(mode_df[mode_df["Status"] != "LIVE"][col_order], use_container_width=True, hide_index=True)

with tab1:
    render_live_tab("Normal", "🟢 Live Normal Strategy Terminal")

with tab2:
    render_live_tab("Reversal", "🔴 Live Reversal Strategy Terminal")

with tab3:
    st.markdown("### 📊 Dual Backtest Engine & Database Logs")
    
    if st.button("▶️ Run 60-Day Backtest", type="primary"):
        with st.spinner("Calculating 60-Day Historical Data via yfinance..."):
            norm_bt, rev_bt = run_60d_backtest(
                SELECTED_STOCKS, FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, 
                ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, 
                TIMEFRAME_MINS, SLIPPAGE_BPS
            )
            st.session_state.norm_bt = norm_bt
            st.session_state.rev_bt = rev_bt

    norm_bt = st.session_state.get("norm_bt")
    rev_bt = st.session_state.get("rev_bt")

    # Normal Strategy Backtest Results
    if norm_bt is not None and not norm_bt.empty:
        st.markdown("#### 🟢 Normal Strategy Backtest Summary")
        
        t_trades = len(norm_bt)
        t_gross = norm_bt["GrossPnL"].sum()
        t_charges = norm_bt["Charges"].sum()
        t_net = round(t_gross - t_charges, 2)
        net_class = "metric-val-green" if t_net >= 0 else "metric-val-red"

        st.markdown(f"""
            <div class="top-pnl-card">
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><span style="font-size: 12px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 18px; font-weight: bold;">{t_trades}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span style="font-size: 18px; font-weight: bold;">{RUPEE}{t_gross:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{t_charges:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{t_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.dataframe(norm_bt, use_container_width=True, hide_index=True)

    # Reversal Strategy Backtest Results
    if rev_bt is not None and not rev_bt.empty:
        st.markdown("---")
        st.markdown("#### 🔴 Reversal Strategy Backtest Summary")
        
        r_trades = len(rev_bt)
        r_gross = rev_bt["GrossPnL"].sum()
        r_charges = rev_bt["Charges"].sum()
        r_net = round(r_gross - r_charges, 2)
        r_net_class = "metric-val-green" if r_net >= 0 else "metric-val-red"

        st.markdown(f"""
            <div class="top-pnl-card">
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><span style="font-size: 12px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 18px; font-weight: bold;">{r_trades}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span style="font-size: 18px; font-weight: bold;">{RUPEE}{r_gross:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{r_charges:.2f}</span></div>
                    <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{r_net_class}">{RUPEE}{r_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.dataframe(rev_bt, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 🗄️ All Live & Closed Trades Master Database")
    db_df = load_db()
    st.dataframe(db_df, use_container_width=True, hide_index=True)

if AUTO_REFRESH:
    time.sleep(15)
    st.rerun()
