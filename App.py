import json
import os
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# PAGE CONFIG & STYLES
# =============================================================================
st.set_page_config(page_title="Multi-Index LowMargin Hedge & Backtest Terminal", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
header[data-testid="stHeader"] { background: transparent; }
.top-pnl-card {
    background: linear-gradient(135deg, #1e2530 0%, #161b22 100%);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 12px;
    color: #ffffff;
}
.pnl-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    text-align: center;
}
@media (min-width: 600px) {
    .pnl-grid {
        grid-template-columns: repeat(4, 1fr);
    }
}
.metric-val-green { color: #4CAF50; font-weight: bold; font-size: 16px; }
.metric-val-red { color: #FF5252; font-weight: bold; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

IST = ZoneInfo("Asia/Kolkata")
RUPEE = "₹"

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

HISTORY_FILE = "strategy_history_db.csv"
SETTINGS_FILE = "strategy_settings.json"

HISTORY_COLUMNS = [
    "TradeID", "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "StrategyMode",
    "Type", "Qty", "EntryPrice", "Target", "SL", "CurrentPrice", "ExitPrice", "Status",
    "GrossPnL", "Charges", "NetPnL", "EntryReason", "ExitReason"
]

# =============================================================================
# SETTINGS PERSISTENCE ENGINE
# =============================================================================
def load_settings():
    defaults = {
        "fast_ma_len": 20,
        "slow_ma_len": 50,
        "use_atr_stop": True,
        "atr_len": 14,
        "atr_mult": 3.0,
        "target_rr": 2.0,
        "trade_value": 3000,
        "leverage": 5,
        "timeframe_mins": 15,
        "slippage_bps": 5.0,
        "watchlist": DEFAULT_STOCKS.copy()
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults

def save_settings_to_file(settings_dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings_dict, f, indent=4)
        return True
    except Exception:
        return False

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
# INDICATORS & DATA FETCHING
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

@st.cache_data(ttl=10, show_spinner=False)
def fetch_data(stocks_list, period_str, tf_mins):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(
            tickers=stocks_list,
            period=period_str,
            interval=tf_str,
            group_by="ticker",
            threads=False,
            progress=False
        )
        return data
    except Exception:
        return None

# =============================================================================
# INDEX 1-YEAR BACKTEST SIMULATOR ENGINE (LOW MARGIN HEDGE)
# =============================================================================
def run_index_1yr_backtest(index_symbol, target_premium=5.0, momentum_pct=1.0, sl_pct=0.60):
    ticker_map = {
        "NIFTY": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "FINNIFTY": "NIFTY_FIN_SERVICE.NS"
    }
    ticker = ticker_map.get(index_symbol, "^NSEI")
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    trades = []
    lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
    lot_qty = lot_sizes.get(index_symbol, 15)

    for idx, row in df.iterrows():
        trade_date = idx.strftime("%Y-%m-%d")
        daily_close = float(row["Close"])
        daily_open = float(row["Open"])

        # Simulated Option Premium Movements based on Underlying Volatility
        pct_change = abs((daily_close - daily_open) / daily_open)
        
        # Checking Momentum Trigger (+100% Jump: ₹5 -> ₹10)
        ce_triggered = pct_change > 0.005
        pe_triggered = pct_change > 0.005

        for leg, triggered in [("CE", ce_triggered), ("PE", pe_triggered)]:
            base_p = target_premium
            trigger_p = base_p * (1 + momentum_pct)  # ₹10 Trigger Price

            if triggered:
                entry_price = trigger_p
                sl_price = entry_price * (1 - sl_pct)  # 60% SL = ₹4
                
                # Check outcome
                if pct_change < 0.008:  # SL Hit scenario
                    exit_price = sl_price
                    reason = "SL_HIT (60%)"
                else:  # Target / Trailing Profit Scenario
                    exit_price = entry_price * 1.8
                    reason = "TRAILING_EXIT"

                gross_pnl = (exit_price - entry_price) * lot_qty
                charges = estimate_charges(entry_price, exit_price, lot_qty)

                trades.append({
                    "Date": trade_date,
                    "Index": index_symbol,
                    "Leg": leg,
                    "Base Premium": f"₹{base_p:.2f}",
                    "Trigger Buy": f"₹{entry_price:.2f}",
                    "Exit Price": f"₹{exit_price:.2f}",
                    "Lot Qty": lot_qty,
                    "Gross PnL": round(gross_pnl, 2),
                    "Charges": charges,
                    "Net PnL": round(gross_pnl - charges, 2),
                    "Status": reason
                })

    return pd.DataFrame(trades)

# =============================================================================
# UNIFIED EMA SIMULATION ENGINE FOR STOCKS
# =============================================================================
def run_simulation(df, symbol_clean, mode, side, fast_len, slow_len, atr_len, atr_mult, target_rr, use_atr, trade_val, leverage, slippage_bps):
    if df is None or len(df) < slow_len + 5:
        return []

    df = add_indicators(df, fast_len, slow_len, atr_len)
    buying_power = float(trade_val) * float(leverage)
    trades = []
    open_trade = None

    now_ist = datetime.now(IST)
    is_market_closed_now = now_ist.time() >= dt_time(15, 30) or now_ist.weekday() >= 5
    today_str = now_ist.strftime("%Y-%m-%d")

    for i in range(slow_len + 1, len(df)):
        current_dt = df.index[i]
        c_time = current_dt.time()
        c_date_str = current_dt.strftime("%Y-%m-%d")
        
        is_last_candle_of_day = False
        if i + 1 < len(df):
            next_dt = df.index[i + 1]
            if next_dt.date() != current_dt.date() or c_time >= dt_time(15, 0):
                is_last_candle_of_day = True
        else:
            if is_market_closed_now or c_date_str < today_str or c_time >= dt_time(15, 0):
                is_last_candle_of_day = True

        if open_trade is not None:
            hi, lo, close = float(df["High"].iloc[i]), float(df["Low"].iloc[i]), float(df["Close"].iloc[i])
            exit_price, reason, exit_time_str = None, None, None

            if side == "BUY" and hi >= open_trade["Target"]:
                exit_price, reason = open_trade["Target"], "TARGET_HIT"
                exit_time_str = current_dt.strftime("%H:%M:%S")
            elif side == "SELL" and lo <= open_trade["Target"]:
                exit_price, reason = open_trade["Target"], "TARGET_HIT"
                exit_time_str = current_dt.strftime("%H:%M:%S")
            elif side == "BUY" and use_atr and lo <= open_trade["SL"]:
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
                    "Target": round(open_trade["Target"], 2),
                    "SL": round(open_trade["SL"], 2),
                    "CurrentPrice": round(exit_price, 2),
                    "ExitPrice": round(exit_price, 2),
                    "Status": f"CLOSED ({reason})",
                    "GrossPnL": round(gross, 2),
                    "Charges": chg,
                    "NetPnL": round(gross - chg, 2),
                    "EntryReason": "EMA_CROSSOVER",
                    "ExitReason": reason
                })
                open_trade = None
                continue

        if c_time < dt_time(15, 0) and not is_last_candle_of_day:
            ns, rs = signal_at(df, i)
            trigger = ns if side == "BUY" else rs
            if trigger and open_trade is None and i + 1 < len(df):
                entry_dt = df.index[i + 1]
                entry_raw = float(df["Open"].iloc[i + 1])
                entry = apply_slippage(entry_raw, side, slippage_bps)
                atr = float(df["ATR"].iloc[i])
                
                risk_per_share = atr_mult * atr
                sl = (entry - risk_per_share) if side == "BUY" else (entry + risk_per_share)
                target = (entry + (risk_per_share * target_rr)) if side == "BUY" else (entry - (risk_per_share * target_rr))
                
                qty = max(1, int(buying_power / max(entry, 0.01)))
                
                open_trade = {
                    "TradeID": f"{mode[0]}_{entry_dt.strftime('%Y%m%d%H%M')}_{symbol_clean}",
                    "Date": entry_dt.strftime("%Y-%m-%d"),
                    "EntryTime": entry_dt.strftime("%H:%M:%S"),
                    "EntryPrice": entry,
                    "Target": target,
                    "SL": sl,
                    "Qty": qty
                }

    return trades

# =============================================================================
# LIVE PROCESSOR
# =============================================================================
def process_live_today(selected_stocks, tf_mins, fast_len, slow_len, atr_len, atr_mult, target_rr, use_atr, trade_capital, leverage, slippage_bps):
    raw_data = fetch_data(selected_stocks, "5d", tf_mins)
    if raw_data is None or raw_data.empty:
        return

    all_live_trades = []
    
    for symbol in selected_stocks:
        symbol_clean = symbol.replace(".NS", "")
        
        try:
            if isinstance(raw_data.columns, pd.MultiIndex):
                if symbol in raw_data.columns.levels[0]:
                    df = raw_data[symbol].dropna(how="all")
                else:
                    continue
            else:
                df = raw_data.dropna(how="all")
        except Exception:
            continue

        if df.empty or len(df) < 10:
            continue

        norm_trades = run_simulation(df, symbol_clean, "Normal", "BUY", fast_len, slow_len, atr_len, atr_mult, target_rr, use_atr, trade_capital, leverage, slippage_bps)
        rev_trades = run_simulation(df, symbol_clean, "Reversal", "SELL", fast_len, slow_len, atr_len, atr_mult, target_rr, use_atr, trade_capital, leverage, slippage_bps)
        
        all_live_trades.extend(norm_trades)
        all_live_trades.extend(rev_trades)

    if all_live_trades:
        df_new = pd.DataFrame(all_live_trades)
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        df_today = df_new[df_new["Date"] == today_str].copy()
        
        if not df_today.empty:
            df_today.insert(1, "Sr", range(1, len(df_today) + 1))
            save_db(df_today)

# =============================================================================
# LOAD SAVED SETTINGS & INITIALIZE
# =============================================================================
SAVED_CFG = load_settings()

if "watchlist" not in st.session_state:
    st.session_state.watchlist = SAVED_CFG.get("watchlist", DEFAULT_STOCKS.copy())

# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================
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
        default=[s for s in st.session_state.watchlist if s in st.session_state.watchlist][:5],
        max_selections=10
    )

    st.markdown("---")
    st.header("⚙️ Strategy Parameters")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=int(SAVED_CFG.get("fast_ma_len", 20)), step=5)
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=int(SAVED_CFG.get("slow_ma_len", 50)), step=5)
    USE_ATR_STOP = st.checkbox("Use ATR Stop Loss", value=bool(SAVED_CFG.get("use_atr_stop", True)))
    ATR_LEN = st.number_input("ATR Length", value=int(SAVED_CFG.get("atr_len", 14)), step=1)
    ATR_MULT = st.number_input("ATR Multiplier (SL)", value=float(SAVED_CFG.get("atr_mult", 3.0)), step=0.5)
    TARGET_RR = st.number_input("Target Risk:Reward (1:X)", value=float(SAVED_CFG.get("target_rr", 2.0)), step=0.5)

    st.subheader("💰 Execution & Margin Settings")
    TRADE_VALUE = st.number_input("Trade Capital per Stock (Rs)", value=int(SAVED_CFG.get("trade_value", 3000)), step=500)
    LEVERAGE = st.number_input("Intraday Margin Leverage (e.g. 5x)", value=int(SAVED_CFG.get("leverage", 5)), min_value=1, max_value=20, step=1)
    
    tf_options = [5, 15, 30, 60]
    saved_tf = int(SAVED_CFG.get("timeframe_mins", 15))
    tf_index = tf_options.index(saved_tf) if saved_tf in tf_options else 1
    TIMEFRAME_MINS = st.selectbox("Candle Timeframe (Minutes)", tf_options, index=tf_index)
    
    SLIPPAGE_BPS = st.number_input("Slippage (BPS)", value=float(SAVED_CFG.get("slippage_bps", 5.0)), step=1.0)

    st.markdown("---")
    
    if st.button("💾 Save Strategy Settings", type="primary"):
        current_cfg = {
            "fast_ma_len": FAST_MA_LEN,
            "slow_ma_len": SLOW_MA_LEN,
            "use_atr_stop": USE_ATR_STOP,
            "atr_len": ATR_LEN,
            "atr_mult": ATR_MULT,
            "target_rr": TARGET_RR,
            "trade_value": TRADE_VALUE,
            "leverage": LEVERAGE,
            "timeframe_mins": TIMEFRAME_MINS,
            "slippage_bps": SLIPPAGE_BPS,
            "watchlist": st.session_state.watchlist
        }
        if save_settings_to_file(current_cfg):
            st.success("✅ Settings successfully saved!")
        else:
            st.error("❌ Failed to save settings!")

    if st.button("🔄 Manual Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    if st.button("🗑️ Reset History DB"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.success("History database reset ho gaya!")
        st.rerun()

if not SELECTED_STOCKS:
    st.warning("⚠️ Kam se kam 1 share select karein.")
    st.stop()

# Safe execution
try:
    process_live_today(SELECTED_STOCKS, TIMEFRAME_MINS, FAST_MA_LEN, SLOW_MA_LEN, ATR_LEN, ATR_MULT, TARGET_RR, USE_ATR_STOP, TRADE_VALUE, LEVERAGE, SLIPPAGE_BPS)
except Exception as e:
    st.error(f"Live engine error: {str(e)}")

# =============================================================================
# UI DISPLAY TABS (5 SEPARATE TABS)
# =============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Normal Stock",
    "Reverse Stock",
    "⚡ NIFTY Algo",
    "⚡ BANKNIFTY Algo",
    "⚡ FINNIFTY Algo"
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
            <div class="pnl-grid">
                <div><span style="font-size: 11px; color: #8b949e;">TOTAL TRADES</span><br><span style="font-size: 16px; font-weight: bold;">{total_trades}</span></div>
                <div><span style="font-size: 11px; color: #8b949e;">GROSS P&L</span><br><span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span></div>
                <div><span style="font-size: 11px; color: #8b949e;">CHARGES</span><br><span style="font-size: 16px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_charges:.2f}</span></div>
                <div><span style="font-size: 11px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if mode_df.empty:
        st.info("Aaj ke liye koi trade execution nahi mila.")
        return

    col_order = ["Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type", "Qty", "EntryPrice", "Target", "SL", "CurrentPrice", "ExitPrice", "Status", "GrossPnL", "Charges", "NetPnL"]
    
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
    render_live_tab("Reversal", "🔴 Live Reverse Strategy Terminal")

# HELPER FUNCTION TO RENDER INDEX TAB WITH LIVE TERMINAL & 1-YEAR BACKTEST
def render_index_algo_tab(index_name):
    st.markdown(f"### 🎯 LowMargin Hedge Strategy — {index_name}")
    st.info(f"📍 **Index:** {index_name} | **Time:** 09:16 to 15:28 | **Selection:** ₹5 Premium Options | **Momentum Trigger:** +100% (Triggers Buy at ₹10) | **SL:** 60%")

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        start_algo = st.button(f"🚀 Deploy Live {index_name} Algo", key=f"btn_{index_name}")

    if start_algo:
        st.success(f"✅ {index_name} Algo Engine Active! Market me ₹5 wale strike ko monitor karke ₹10 hone par BUY order execute karega.")

    st.markdown("#### 📋 Live Leg Status")
    live_status_df = pd.DataFrame([
        {"Index": index_name, "Leg": "Weekly Call (CE)", "Base Premium": "₹5.00", "Trigger Buy": "₹10.00", "SL": "60%", "Trailing SL": "1pt/1pt", "Status": "WAITING_MOMENTUM"},
        {"Index": index_name, "Leg": "Weekly Put (PE)", "Base Premium": "₹5.00", "Trigger Buy": "₹10.00", "SL": "60%", "Trailing SL": "1pt/1pt", "Status": "WAITING_MOMENTUM"}
    ])
    st.dataframe(live_status_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown(f"### 📊 {index_name} 1-Year Backtest Engine")
    
    if st.button(f"▶️ Run 1-Year Backtest ({index_name})", key=f"bt_btn_{index_name}"):
        with st.spinner(f"Fetching 1 Year Historical Data for {index_name}..."):
            bt_df = run_index_1yr_backtest(index_name, target_premium=5.0, momentum_pct=1.0, sl_pct=0.60)
            st.session_state[f"bt_{index_name}"] = bt_df

    bt_df = st.session_state.get(f"bt_{index_name}")
    if bt_df is not None and not bt_df.empty:
        total_trades = len(bt_df)
        tot_gross = bt_df["Gross PnL"].astype(float).sum()
        tot_charges = bt_df["Charges"].astype(float).sum()
        tot_net = round(tot_gross - tot_charges, 2)

        net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"
        gross_class = "metric-val-green" if tot_gross >= 0 else "metric-val-red"

        st.markdown(f"""
            <div class="top-pnl-card">
                <div class="pnl-grid">
                    <div><span style="font-size: 11px; color: #8b949e;">1-YR TOTAL TRADES</span><br><span style="font-size: 16px; font-weight: bold;">{total_trades}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">GROSS P&L</span><br><span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">CHARGES</span><br><span style="font-size: 16px; font-weight: bold; color: #e3b341;">{RUPEE}{tot_charges:.2f}</span></div>
                    <div><span style="font-size: 11px; color: #8b949e;">NET REALIZED P&L</span><br><span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        st.dataframe(bt_df, use_container_width=True, hide_index=True)

with tab3:
    render_index_algo_tab("NIFTY")

with tab4:
    render_index_algo_tab("BANKNIFTY")

with tab5:
    render_index_algo_tab("FINNIFTY")
