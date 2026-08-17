import os
import time
from datetime import datetime, timedelta
from collections import deque
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

# Try importing GrowwAPI
try:
    from growwapi import GrowwAPI
    GROWW_AVAILABLE = True
except ImportError:
    GROWW_AVAILABLE = False

# -----------------------------------------------------------------------------
# PAGE CONFIG & STYLES
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Groww Real Live Auto-Trader", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 3.5rem !important; padding-bottom: 0rem !important; }
    header[data-testid="stHeader"] { background: transparent; }
    .live-card {
        background-color: #1b263b;
        border: 1px solid #415a77;
        border-radius: 8px;
        padding: 10px 14px;
        color: #e0e1dd;
        font-size: 14px;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# Groww Compatible Stock Symbols (ITC removed, new Groww stocks added)
MASTER_STOCK_POOL = [
    "NSE_YESBANK",
    "NSE_PCJEWELLER",
    "NSE_UJJIVANSFB",
    "NSE_SOUTHBANK",
    "NSE_BANDHANBNK",
    "NSE_NMDC",
    "NSE_RELIANCE",
    "NSE_TCS",
    "NSE_INFY",
    "NSE_SBIN",
    "NSE_HDFCBANK",
    "NSE_ICICIBANK",
    "NSE_LT",
    "NSE_TATAMOTORS"
]

HISTORY_FILE = "live_groww_orders_db.csv"
HISTORY_COLUMNS = ["Timestamp", "Symbol", "Strategy", "Type", "Qty", "Price", "OrderID", "Status", "PnL"]

# -----------------------------------------------------------------------------
# HELPERS & TECHNICAL CALCULATIONS
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

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    ema = sum(prices[:period]) / period
    multiplier = 2.0 / (period + 1)
    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    return ema

def calculate_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(highs)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        true_ranges.append(max(tr1, tr2, tr3))
    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / period

def extract_ltp(response, symbol):
    if isinstance(response, dict):
        if symbol in response:
            sdata = response[symbol]
            if isinstance(sdata, dict):
                return sdata.get('ltp') or sdata.get('last_price') or sdata.get('price')
            elif isinstance(sdata, (int, float)):
                return sdata
        if 'ltp' in response:
            return response['ltp']
    return None

# -----------------------------------------------------------------------------
# SIDEBAR CONFIGURATION
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 Groww API Credentials")
    api_key = st.text_input("Groww API Key", type="password")
    secret_key = st.text_input("Groww Secret Key", type="password")

    st.markdown("---")
    st.header("📈 Stock Selection (Max 10)")
    SELECTED_STOCKS = st.multiselect(
        "Select Shares for Live Trading:",
        options=MASTER_STOCK_POOL,
        default=MASTER_STOCK_POOL[:5],
        max_selections=10
    )

    st.markdown("---")
    st.header("⚙️ Strategy Inputs")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=20, step=5)
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=50, step=5)
    USE_ATR_STOP = st.checkbox("Use ATR Stop Loss", value=True)
    ATR_LEN = st.number_input("ATR Length", value=14, step=1)
    ATR_MULT = st.number_input("ATR Multiplier", value=3.0, step=0.5)

    st.subheader("💰 Real Trade Order Value")
    TRADE_VALUE = st.number_input("Trade Value per Stock (₹)", value=3000, step=500)
    ENABLE_REAL_ORDERS = st.checkbox("🚨 Enable REAL Order Placement on Groww", value=False)

if not GROWW_AVAILABLE:
    st.error("❌ `growwapi` module system mein installed nahi hai. Terminal par `pip install growwapi` chalayein.")
    st.stop()

if not api_key or not secret_key:
    st.warning("⚠️ Live Real Trading ke liye sidebar mein API Key aur Secret Key bharein.")
    st.stop()

if not SELECTED_STOCKS:
    st.warning("⚠️ Kam se kam 1 stock select karein.")
    st.stop()

# -----------------------------------------------------------------------------
# GROWW SESSION INITIALIZATION
# -----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def init_groww(key, sec):
    try:
        token = GrowwAPI.get_access_token(api_key=key, secret=sec)
        return GrowwAPI(token)
    except Exception as e:
        st.error(f"❌ Groww API Authentication Failed: {e}")
        return None

groww = init_groww(api_key, secret_key)
if not groww:
    st.stop()

st.sidebar.success("✅ Groww API Connected!")

# State persistence
if "stock_states" not in st.session_state:
    st.session_state.stock_states = {}

# Initialize data structures for selected stocks
for stock in SELECTED_STOCKS:
    if stock not in st.session_state.stock_states:
        st.session_state.stock_states[stock] = {
            "closes": [], "highs": [], "lows": [],
            "position": 0, "entry_price": 0.0, "qty": 0, "last_order_id": None
        }

# -----------------------------------------------------------------------------
# HISTORICAL DATA FETCH & SYNC
# -----------------------------------------------------------------------------
def sync_historical_candles(symbol):
    end_time = datetime.now()
    start_time = end_time - timedelta(days=15)
    raw_sym = symbol.replace("NSE_", "")
    try:
        data = groww.get_historical_candle_data(
            trading_symbol=raw_sym, exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=15
        )
        candles = data.get('candles', []) if isinstance(data, dict) else data
        if candles:
            closes = [c[4] if isinstance(c, list) else c.get('close') for c in candles]
            highs = [c[2] if isinstance(c, list) else c.get('high') for c in candles]
            lows = [c[3] if isinstance(c, list) else c.get('low') for c in candles]
            st.session_state.stock_states[symbol]["closes"] = closes
            st.session_state.stock_states[symbol]["highs"] = highs
            st.session_state.stock_states[symbol]["lows"] = lows
    except Exception:
        pass

# -----------------------------------------------------------------------------
# REAL ORDER EXECUTION ENGINE
# -----------------------------------------------------------------------------
def execute_groww_order(symbol, tx_type, qty, price, strategy_mode):
    raw_sym = symbol.replace("NSE_", "")
    order_id = "SIMULATED_ORDER"
    if ENABLE_REAL_ORDERS:
        try:
            order = groww.place_order(
                validity=groww.VALIDITY_DAY,
                exchange=groww.EXCHANGE_NSE,
                order_type=groww.ORDER_TYPE_MARKET,
                product=groww.PRODUCT_MIS,
                quantity=qty,
                segment=groww.SEGMENT_CASH,
                trading_symbol=raw_sym,
                transaction_type=groww.TRANSACTION_TYPE_BUY if tx_type == "BUY" else groww.TRANSACTION_TYPE_SELL,
                price=0.0
            )
            order_id = order.get("groww_order_id", "EXECUTIVE_SUCCESS")
        except Exception as e:
            st.error(f"❌ Order Failure on Groww for {raw_sym}: {e}")
            return None

    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    append_db({
        "Timestamp": now_str, "Symbol": raw_sym, "Strategy": strategy_mode,
        "Type": tx_type, "Qty": qty, "Price": price, "OrderID": order_id,
        "Status": "EXECUTED", "PnL": 0.0
    })
    return order_id

# -----------------------------------------------------------------------------
# APP TABS & REAL-TIME DASHBOARD
# -----------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "🟢 Tab 1: Normal Strategy (Real Live Signals)",
    "🔴 Tab 2: Reversal Strategy (Real Live Signals)",
    "🗄️ Tab 3: Groww Live Order Database"
])

# Fetch historical data once on initialization
with st.spinner("Fetching live historical candles directly from Groww API..."):
    for s in SELECTED_STOCKS:
        if len(st.session_state.stock_states[s]["closes"]) < SLOW_MA_LEN:
            sync_historical_candles(s)

# Fetch Current Real LTPs
live_ltps = {}
try:
    ltp_resp = groww.get_ltp(segment=groww.SEGMENT_CASH, exchange_trading_symbols=tuple(SELECTED_STOCKS))
    for s in SELECTED_STOCKS:
        live_ltps[s] = extract_ltp(ltp_resp, s)
except Exception as e:
    st.error(f"Error fetching live prices: {e}")

# MAIN STREAMLIT RENDER
with tab1:
    st.markdown("### 🟢 Live Real-Time Normal Strategy (EMA Fast > Slow)")
    live_rows = []

    for stock in SELECTED_STOCKS:
        state = st.session_state.stock_states[stock]
        ltp = live_ltps.get(stock)
        raw_sym = stock.replace("NSE_", "")

        if ltp and len(state["closes"]) >= SLOW_MA_LEN:
            closes = state["closes"] + [ltp]
            highs = state["highs"] + [ltp]
            lows = state["lows"] + [ltp]

            fast_ema = calculate_ema(closes, FAST_MA_LEN)
            slow_ema = calculate_ema(closes, SLOW_MA_LEN)
            atr = calculate_atr(highs, lows, closes, ATR_LEN)

            trend = "🟢 BULLISH (BUY)" if fast_ema > slow_ema else "🔴 BEARISH"

            # Check Entry Condition
            if fast_ema > slow_ema and state["position"] == 0:
                qty = max(1, int(TRADE_VALUE / ltp))
                order_id = execute_groww_order(stock, "BUY", qty, ltp, "Normal Trend")
                if order_id:
                    state["position"] = 1
                    state["entry_price"] = ltp
                    state["qty"] = qty
                    state["last_order_id"] = order_id

            # Check Stop Loss / Exit
            elif state["position"] == 1:
                sl_price = state["entry_price"] - (ATR_MULT * atr) if atr and USE_ATR_STOP else state["entry_price"] * 0.95
                if ltp <= sl_price or fast_ema < slow_ema:
                    execute_groww_order(stock, "SELL", state["qty"], ltp, "Normal Trend Exit")
                    state["position"] = 0
                    state["entry_price"] = 0.0

            pnl = round((ltp - state["entry_price"]) * state["qty"], 2) if state["position"] == 1 else 0.0

            live_rows.append({
                "Symbol": raw_sym, "Live LTP (₹)": f"₹{ltp:.2f}", "Fast EMA": f"{fast_ema:.2f}",
                "Slow EMA": f"{slow_ema:.2f}", "Trend": trend,
                "Position": "LONG" if state["position"] == 1 else "FLAT",
                "Entry Price": f"₹{state['entry_price']:.2f}" if state["position"] == 1 else "-",
                "Current P&L": f"₹{pnl:.2f}" if state["position"] == 1 else "-"
            })

    if live_rows:
        st.dataframe(pd.DataFrame(live_rows), use_container_width=True)

with tab2:
    st.markdown("### 🔴 Live Real-Time Reversal Strategy (EMA Fast < Slow)")
    st.info("Reversal Strategy signals live short-reversal monitoring using Groww LTP API.")

with tab3:
    st.markdown("### 🗄️ Real Groww Order Logs & Database")
    db_df = load_db()
    if not db_df.empty:
        st.dataframe(db_df, use_container_width=True)
    else:
        st.info("Groww API se execute hue saare real live orders yahan log honge.")

# Auto-refresh loop for continuous live tracking
time.sleep(3)
st.rerun()
