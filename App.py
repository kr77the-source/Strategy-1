import os
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# PAGE CONFIG & STYLES
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
    try:
        df.to_csv(HISTORY_FILE, index=False)
    except Exception:
        pass

# =============================================================================
# INDICATORS & MATHS
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

@st.cache_data(ttl=15, show_spinner=False)
def fetch_data(stocks_list, period_str, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        return yf.download(
            tickers=" ".join(stocks_list),
            period=period_str,
            interval=tf_str,
            group_by="ticker",
            threads=True,
            progress=False
        )
    except Exception:
        return {}

# =============================================================================
# UNIFIED SIMULATION ENGINE (SHARED BY LIVE & BACKTEST)
# =============================================================================
def run_simulation(df, symbol_clean, mode, side, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_val, leverage, slippage_bps):
    if df is None or len(df) < slow_len + 5:
        return []

    df = add_indicators(df, fast_len, slow_len, atr_len)
    buying_power = float(trade_val) * float(leverage)
    trades = []
    open_trade = None

    for i in range(slow_len + 1, len(df)):
        current_dt = df.index[i]
        c_time = current_dt.time()
        
        # Determine if next bar exists or if candle is end of day
        is_last_candle_of_day = False
        if i + 1 < len(df):
            next_dt = df.index[i + 1]
            if next_dt.date() != current_dt.date() or c_time >= dt_time(15, 15):
                is_last_candle_of_day = True
        else:
            if c_time >= dt_time(15, 15):
                is_last_candle_of_day = True

        # Check Exits for active trade
        if open_trade is not None:
            hi, lo, close = float(df["High"].iloc[i]), float(df["Low"].iloc[i]), float(df["Close"].iloc[i])
            exit_price, reason, exit_time_str = None, None, None

            if side == "BUY" and use_atr and lo <= open_trade["SL"]:
                exit_price, reason = open_trade["SL"], "SL_HIT"
                exit_time_str = current_dt.strftime("%H:%M:%S")
            elif side == "SELL" and use_atr and hi >= open_trade["SL"]:
                exit_price, reason = open_trade["SL"], "SL_HIT"
                exit_time_str = current_dt.strftime("%H:%M:%S")
            elif is_last_candle_of_day:
                exit_price = apply_slippage(close, "SELL" if side == "BUY" else "BUY", slippage_bps)
                reason = "EOD_SQUAREOFF"
                exit_time_str = "15:25:00"
            else:
                ns, rs = signal_at(df, i)
                if (side == "BUY" and rs) or (side == "SELL" and ns):
                    exit_price = apply_slippage(float(df["Open"].iloc[i]), "SELL" if side == "BUY" else "BUY", slippage_bps)
                    reason = "OPPOSITE_SIGNAL"
                    exit_time_str = current_dt.strftime("%H:%M:%S")

            if exit_price is not None:
                entry, qty = open_trade["EntryPrice"], open_trade["Qty"]
                gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                chg = estimate_charges(entry, exit_price, qty)
                
                trades.append({
                    "TradeID": open_trade["TradeID"],
                    "Date": open_trade["Date"],
                    "EntryTime": open_trade["EntryTime"],
                    "ExitTime": exit_time_str,
                    "Symbol": symbol_clean,
                    "StrategyMode": mode,
                    "Type": side,
                    "Qty": qty,
                    "EntryPrice": round(entry, 2),
                    "CurrentPrice": round(exit_price, 2),
                    "ExitPrice": round(exit_price, 2),
                    "SL": round(open_trade["SL"], 2),
                    "Status": f"CLOSED ({reason})",
                    "GrossPnL": round(gross, 2),
                    "Charges": chg,
                    "NetPnL": round(gross - chg, 2),
                    "EntryReason": "EMA_CROSSOVER",
                    "ExitReason": reason
                })
                open_trade = None
                continue

        # Check Entries
        if c_time < dt_time(15, 0) and not is_last_candle_of_day:
            ns, rs = signal_at(df, i)
            trigger = ns if side == "BUY" else rs
            if trigger and open_trade is None and i + 1 < len(df):
                entry_dt = df.index[i + 1]
                entry_raw = float(df["Open"].iloc[i + 1])
                entry = apply_slippage(entry_raw, side, slippage_bps)
                atr = float(df["ATR"].iloc[i])
                sl = (entry - atr_mult * atr) if side == "BUY" else (entry + atr_mult * atr)
                qty = max(1, int(buying_power / max(entry, 0.01)))
                
                open_trade = {
                    "TradeID": f"{mode[0]}_{entry_dt.strftime('%Y%m%d%H%M')}_{symbol_clean}",
                    "Date": entry_dt.strftime("%Y-%m-%d"),
                    "EntryTime": entry_dt.strftime("%H:%M:%S"),
                    "EntryPrice": entry,
                    "SL": sl,
                    "Qty": qty
                }

    # If position is still open right now in live market
    if open_trade is not None:
        latest_close = float(df["Close"].iloc[-1])
        entry, qty = open_trade["EntryPrice"], open_trade["Qty"]
        gross = (latest_close - entry) * qty if side == "BUY" else (entry - latest_close) * qty
        chg = estimate_charges(entry, latest_close, qty)
        
        trades.append({
            "TradeID": open_trade["TradeID"],
            "Date": open_trade["Date"],
            "EntryTime": open_trade["EntryTime"],
            "ExitTime": "-",
            "Symbol": symbol_clean,
            "StrategyMode": mode,
            "Type": side,
            "Qty": qty,
            "EntryPrice": round(entry, 2),
            "CurrentPrice": round(latest_close, 2),
            "ExitPrice": "-",
            "SL": round(open_trade["SL"], 2),
            "Status": "LIVE",
            "GrossPnL": round(gross, 2),
            "Charges": chg,
            "NetPnL": round(gross - chg, 2),
            "EntryReason": "EMA_CROSSOVER",
            "ExitReason": "-"
        })

    return trades

# =============================================================================
# PROCESS TODAY'S LIVE TRADES
# =============================================================================
def process_live_today(selected_stocks, tf_mins, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_capital, leverage, slippage_bps):
    raw_data = fetch_data(selected_stocks, "5d", tf_mins)
    if raw_data is None or (isinstance(raw_data, dict) and not raw_data):
        return

    all_live_trades = []
    
    for symbol in selected_stocks:
        symbol_clean = symbol.replace(".NS", "")
        df = raw_data[symbol].dropna(how="all") if len(selected_stocks) > 1 else raw_data
        
        # Run Simulation for Normal (BUY)
        norm_trades = run_simulation(df, symbol_clean, "Normal", "BUY", fast_len, slow_len, atr_len, atr_mult, use_atr, trade_capital, leverage, slippage_bps)
        # Run Simulation for Reversal (SELL)
        rev_trades = run_simulation(df, symbol_clean, "Reversal", "SELL", fast_len, slow_len, atr_len, atr_mult, use_atr, trade_capital, leverage, slippage_bps)
        
        all_live_trades.extend(norm_trades)
        all_live_trades.extend(rev_trades)

    if all_live_trades:
        df_new = pd.DataFrame(all_live_trades)
        
        # Filter for today's trades only for live view
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        df_today = df_new[df_new["Date"] == today_str].copy()
        
        if not df_today.empty:
            df_today.insert(1, "Sr", range(1, len(df_today) + 1))
            save_db(df_today)

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
        st.success("History database reset ho gaya!")
        st.rerun()

if not SELECTED_STOCKS:
    st.warning("⚠️ Kam se kam 1 share select karein.")
    st.stop()

# Run Live Execution
process_live_today(SELECTED_STOCKS, TIMEFRAME_MINS, FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, SLIPPAGE_BPS)

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
                <div><span style="font-size: 12px; color: #8b949e;">TRADES TODAY</span><br><span style="font-size: 18px; font-weight: bold;">{total_trades}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">GROSS P&L</span><br><span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">CHARGES</span><br><span style="font-size: 18px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_charges:.2f}</span></div>
                <div><span style="font-size: 12px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if mode_df.empty:
        st.info("Aaj ke liye koi trade execution nahi mila.")
        return

    col_order = ["Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type", "Qty", "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status", "GrossPnL", "Charges", "NetPnL"]
    
    st.markdown("#### 🟢 Active Positions")
    active_df = mode_df[mode_df["Status"] == "LIVE"]
    if not active_df.empty:
        st.dataframe(active_df[col_order], use_container_width=True, hide_index=True)
    else:
        st.caption("Koi active position nahi hai.")

    st.markdown("#### 🗄️ Closed Trades Today")
    closed_df = mode_df[mode_df["Status"] != "LIVE"]
    if not closed_df.empty:
        st.dataframe(closed_df[col_order], use_container_width=True, hide_index=True)
    else:
        st.caption("Koi closed trade nahi hai.")

with tab1:
    render_live_tab("Normal", "🟢 Live Normal Strategy Terminal")

with tab2:
    render_live_tab("Reversal", "🔴 Live Reversal Strategy Terminal")

with tab3:
    st.markdown("### 📊 Dual 60-Day Backtest Engine")
    
    if st.button("▶️ Run 60-Day Backtest", type="primary"):
        with st.spinner("Calculating 60-Day Historical Data..."):
            bt_data = fetch_data(SELECTED_STOCKS, "60d", TIMEFRAME_MINS)
            norm_list, rev_list = [], []
            
            for sym in SELECTED_STOCKS:
                sym_clean = sym.replace(".NS", "")
                df_sym = bt_data[sym].dropna(how="all") if len(SELECTED_STOCKS) > 1 else bt_data
                
                n_tr = run_simulation(df_sym, sym_clean, "Normal", "BUY", FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, SLIPPAGE_BPS)
                r_tr = run_simulation(df_sym, sym_clean, "Reversal", "SELL", FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, ATR_MULT, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, SLIPPAGE_BPS)
                
                norm_list.extend(n_tr)
                rev_list.extend(r_tr)
                
            st.session_state.norm_bt = pd.DataFrame(norm_list)
            st.session_state.rev_bt = pd.DataFrame(rev_list)

    norm_bt = st.session_state.get("norm_bt")
    rev_bt = st.session_state.get("rev_bt")

    if norm_bt is not None and not norm_bt.empty:
        st.markdown("#### 🟢 Normal Strategy 60-Day Backtest Results")
        norm_bt.insert(0, "Sr", range(1, len(norm_bt) + 1))
        st.dataframe(norm_bt, use_container_width=True, hide_index=True)

    if rev_bt is not None and not rev_bt.empty:
        st.markdown("---")
        st.markdown("#### 🔴 Reversal Strategy 60-Day Backtest Results")
        rev_bt.insert(0, "Sr", range(1, len(rev_bt) + 1))
        st.dataframe(rev_bt, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 🗄️ Today's Master Database")
    db_df = load_db()
    st.dataframe(db_df, use_container_width=True, hide_index=True)

if AUTO_REFRESH:
    time.sleep(15)
    st.rerun()
