import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Live Tracker & PnL",
    page_icon="📈",
    layout="wide"
)

# App Header
st.title("🚀 Zero-Hero Scanner & Live Trade PnL Tracker")
st.markdown("##### Real-Time ₹3 - ₹5 Strike Tracking • Lot Management & Trade Log")
st.markdown("---")

# --- INITIALIZE SESSION STATE FOR TRADE HISTORY ---
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []

# --- TOP CONTROLS ---
top_col1, top_col2, top_col3, top_col4 = st.columns(4)

with top_col1:
    selected_symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

with top_col2:
    selected_expiry = st.selectbox("Select Expiry", ["Current Weekly", "Next Weekly", "Monthly"])

with top_col3:
    # Lot Selector starting from 1
    lot_multiplier = st.number_input("Select Lots", min_value=1, max_value=50, value=1, step=1)

with top_col4:
    st.markdown("### ") 
    auto_refresh = st.checkbox("🔄 Auto-Run Every 2 Sec", value=False)

st.markdown("---")

# --- ADVANCED SETTINGS EXPANDER ---
with st.expander("⚙️ Strategy Settings (Time & Direction)"):
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        enable_time_filter = st.checkbox("Enable Safe Time Filter (Scan after 9:15 AM onwards)", value=True)
    with col_f2:
        trade_direction = st.selectbox("Allowed Direction", ["BOTH (CE & PE)", "ONLY CALL (CE)", "ONLY PUT (PE)"])

# --- FETCH DATA FROM NSE ---
@st.cache_data(ttl=2)
def fetch_live_data(symbol):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    }
    try:
        session = requests.Session()
        home_resp = session.get("https://www.nseindia.com", headers=headers, timeout=5)
        cookies = home_resp.cookies
        response = session.get(url, headers=headers, cookies=cookies, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

# --- TIME CHECK LOGIC ---
current_time = datetime.now().time()
market_ready = True

if enable_time_filter:
    # 9:15 AM start check
    market_open_time = datetime.strptime("09:15:00", "%H:%M:%S").time()
    if current_time < market_open_time:
        market_ready = False

# Index Lot Sizes mapping (Approx standard sizes for investment calculation)
lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
current_lot_size = lot_sizes.get(selected_symbol, 25) * lot_multiplier

# Fetching Data
data = fetch_live_data(selected_symbol)

if data and 'records' in data:
    spot_price = data['records']['underlyingValue']
    records = data['records']['data']
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label=f"{selected_symbol} Live Spot", value=f"₹ {spot_price:,.2f}")
    with col2:
        st.metric(label="Active Expiry", value=selected_expiry)
    with col3:
        st.metric(label="Total Qty (Lots x Size)", value=f"{current_lot_size} Qty")

    st.markdown("---")
    st.subheader(f"🎯 Live Zero-Hero Signals (₹3 - ₹5)")

    if not market_ready:
        st.warning(f"⏳ Market 9:15 AM par shuru hoga (Current Time: {current_time.strftime('%H:%M:%S')}).")
    else:
        signals = []
        for item in records:
            # Check Call Option (CE)
            if 'CE' in item and trade_direction in ["BOTH (CE & PE)", "ONLY CALL (CE)"]:
                ce_ltp = item['CE'].get('lastPrice', 0)
                ce_strike = item['CE'].get('strikePrice', 0)
                if 3.0 <= ce_ltp <= 5.0:
                    invest_amt = ce_ltp * current_lot_size
                    signals.append({
                        "Type": "CALL (CE)",
                        "Strike": ce_strike,
                        "Premium (₹)": ce_ltp,
                        "Total Invest (₹)": round(invest_amt, 2),
                        "Max Risk": f"₹{250 * lot_multiplier} - ₹{300 * lot_multiplier}",
                        "Action": "BUY"
                    })
            
            # Check Put Option (PE)
            if 'PE' in item and trade_direction in ["BOTH (CE & PE)", "ONLY PUT (PE)"]:
                pe_ltp = item['PE'].get('lastPrice', 0)
                pe_strike = item['PE'].get('strikePrice', 0)
                if 3.0 <= pe_ltp <= 5.0:
                    invest_amt = pe_ltp * current_lot_size
                    signals.append({
                        "Type": "PUT (PE)",
                        "Strike": pe_strike,
                        "Premium (₹)": pe_ltp,
                        "Total Invest (₹)": round(invest_amt, 2),
                        "Max Risk": f"₹{250 * lot_multiplier} - ₹{300 * lot_multiplier}",
                        "Action": "BUY"
                    })

        if len(signals) > 0:
            df_signals = pd.DataFrame(signals)
            st.table(df_signals)
            
            # Auto-log live signals into history table for demo/tracking
            entry_timestamp = datetime.now().strftime("%H:%M:%S")
            for sig in signals[:1]: # Log top active signal for tracking demo
                # Avoid duplicate immediate entries
                if not any(t['Strike'] == sig['Strike'] and t['Status'] == 'OPEN' for t in st.session_state.trade_history):
                    st.session_state.trade_history.append({
                        "Time In": entry_timestamp,
                        "Time Out": "Running...",
                        "Symbol": selected_symbol,
                        "Type": sig['Type'],
                        "Strike": sig['Strike'],
                        "Entry Price": sig['Premium (₹)'],
                        "Exit Price": "-",
                        "Status": "OPEN",
                        "PnL (₹)": "Live..."
                    })
        else:
            st.info("Is samay ₹3 se ₹5 ki range mein koi option active nahi hai.")
else:
    st.warning("⚠️ Market closed hai. Live market hours mein data yahin dikhega.")

# --- BOTTOM SECTION: PNL & TRADE HISTORY LOG ---
st.markdown("---")
st.subheader("📊 Live Trade PnL & History Log")

if len(st.session_state.trade_history) > 0:
    df_history = pd.DataFrame(st.session_state.trade_history)
    st.dataframe(df_history, use_container_width=True)
    
    col_bt1, col_bt2 = st.columns(2)
    with col_bt1:
        if st.button("🔴 Close All Open Trades (Book PnL)"):
            exit_timestamp = datetime.now().strftime("%H:%M:%S")
            for trade in st.session_state.trade_history:
                if trade['Status'] == 'OPEN':
                    trade['Time Out'] = exit_timestamp
                    trade['Exit Price'] = trade['Entry Price'] * 1.5 # Simulated target hit
                    trade['Status'] = 'CLOSED'
                    trade['PnL (₹)'] = f"+₹{round((1.5 - trade['Entry Price']) * current_lot_size, 2)}"
            st.rerun()
    with col_bt2:
        if st.button("🗑️ Clear History"):
            st.session_state.trade_history = []
            st.rerun()
else:
    st.info("Abhi koi trade history record nahi hui hai. Market chalu hone par trades yahan log hongi.")

# --- AUTO-RUN LOGIC ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
