import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Live Tracker",
    page_icon="📈",
    layout="wide"
)

# Custom CSS for clean mobile layout
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    hr {
        margin-top: 0.5rem !important;
        margin-bottom: 0.8rem !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- INITIALIZE SESSION STATE ---
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []

# --- TOP CONTROLS (Normal Vertical Layout) ---
selected_symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
selected_expiry = st.selectbox("Select Expiry", ["Current Weekly", "Next Weekly", "Monthly"])
lot_multiplier = st.number_input("Select Lots", min_value=1, max_value=50, value=1, step=1)
auto_refresh = st.checkbox("🔄 Auto-Run", value=False)

st.markdown("---")

# --- FETCH DATA FROM NSE ---
@st.cache_data(ttl=2)
def fetch_live_data(symbol):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
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

data = fetch_live_data(selected_symbol)

if data and 'records' in data:
    spot_price = data['records']['underlyingValue']
    records = data['records']['data']
    
    m1, m2 = st.columns(2)
    with m1:
        st.metric(label=f"{selected_symbol} Spot", value=f"₹ {spot_price:,.2f}")
    with m2:
        lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25, "MIDCPNIFTY": 50}
        current_lot_size = lot_sizes.get(selected_symbol, 25) * lot_multiplier
        st.metric(label="Total Qty", value=f"{current_lot_size} Qty")

    st.markdown("---")
    st.subheader("🎯 Active Signals (₹3 - ₹5)")

    signals = []
    for item in records:
        if 'CE' in item:
            ce_ltp = item['CE'].get('lastPrice', 0)
            ce_strike = item['CE'].get('strikePrice', 0)
            if 3.0 <= ce_ltp <= 5.0:
                invest_amt = ce_ltp * current_lot_size
                signals.append({
                    "Type": "CALL",
                    "Strike": ce_strike,
                    "Price": ce_ltp,
                    "Total (₹)": round(invest_amt, 2),
                    "Risk": f"₹{250 * lot_multiplier}",
                    "Action": "BUY"
                })
        
        if 'PE' in item:
            pe_ltp = item['PE'].get('lastPrice', 0)
            pe_strike = item['PE'].get('strikePrice', 0)
            if 3.0 <= pe_ltp <= 5.0:
                invest_amt = pe_ltp * current_lot_size
                signals.append({
                    "Type": "PUT",
                    "Strike": pe_strike,
                    "Price": pe_ltp,
                    "Total (₹)": round(invest_amt, 2),
                    "Risk": f"₹{250 * lot_multiplier}",
                    "Action": "BUY"
                })

    if len(signals) > 0:
        df_signals = pd.DataFrame(signals)
        st.table(df_signals)
        
        entry_timestamp = datetime.now().strftime("%H:%M:%S")
        for sig in signals[:1]:
            if not any(t['Strike'] == sig['Strike'] and t['Status'] == 'OPEN' for t in st.session_state.trade_history):
                st.session_state.trade_history.append({
                    "In": entry_timestamp,
                    "Out": "-",
                    "Symbol": selected_symbol,
                    "Type": sig['Type'],
                    "Strike": sig['Strike'],
                    "Entry": sig['Price'],
                    "Status": "OPEN",
                    "PnL": "Live..."
                })
    else:
        st.info("Is samay ₹3 - ₹5 range mein koi option active nahi hai.")

# --- PNL & TRADE HISTORY LOG ---
st.markdown("---")
st.subheader("📊 Trade History & PnL")

if len(st.session_state.trade_history) > 0:
    df_history = pd.DataFrame(st.session_state.trade_history)
    st.dataframe(df_history, use_container_width=True)
    
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🔴 Close All Trades"):
            exit_timestamp = datetime.now().strftime("%H:%M:%S")
            for trade in st.session_state.trade_history:
                if trade['Status'] == 'OPEN':
                    trade['Out'] = exit_timestamp
                    trade['Status'] == 'CLOSED'
                    trade['PnL'] = "Booked"
            st.rerun()
    with b2:
        if st.button("🗑️ Clear Log"):
            st.session_state.trade_history = []
            st.rerun()
else:
    st.info("Koi trade log nahi hai.")

# --- AUTO-RUN LOGIC ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
