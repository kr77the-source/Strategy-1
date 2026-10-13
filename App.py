import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# Page Configuration
st.set_page_config(
    page_title="Advanced Zero-Hero Scanner",
    page_icon="📈",
    layout="wide"
)

# App Header
st.title("🚀 Advanced Zero-Hero Option Scanner")
st.markdown("##### With Time Filter & Real-Time NSE Data (₹3 - ₹5)")
st.markdown("---")

# --- TOP CONTROLS ---
top_col1, top_col2, top_col3 = st.columns(3)

with top_col1:
    selected_symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

with top_col2:
    selected_expiry = st.selectbox("Select Expiry", ["Current Weekly", "Next Weekly", "Monthly"])

with top_col3:
    st.markdown("### ") 
    auto_refresh = st.checkbox("🔄 Auto-Run Every 2 Seconds", value=False)

st.markdown("---")

# --- ADVANCED SETTINGS EXPANDER (Filters) ---
with st.expander("⚙️ Advanced Strategy Rules (Click to Configure)"):
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        # Time filter for Zero-Hero (Expiry day second half is best)
        enable_time_filter = st.checkbox("Enable Safe Time Filter (Scan only after 1:00 PM)", value=True)
    with col_f2:
        # Direction filter
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
    # 13:00 is 1:00 PM
    allowed_start_time = datetime.strptime("13:00:00", "%H:%M:%S").time()
    if current_time < allowed_start_time:
        market_ready = False

# Fetching Data
data = fetch_live_data(selected_symbol)

if data and 'records' in data:
    spot_price = data['records']['underlyingValue']
    records = data['records']['data']
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label=f"{selected_symbol} Live Spot Price", value=f"₹ {spot_price:,.2f}")
    with col2:
        st.metric(label="Active Selected Expiry", value=selected_expiry)

    st.markdown("---")
    st.subheader(f"🎯 Filtered Zero-Hero Signals (₹3 - ₹5)")

    if not market_ready:
        st.warning(f"⏳ Safe Time Filter Active: Dopahar 1:00 PM se pehle Zero-Hero scan pause hai (Current Time: {current_time.strftime('%H:%M:%S')}). Aap advanced settings se ise off kar sakte hain.")
    else:
        signals = []
        for item in records:
            # Check Call Option (CE)
            if 'CE' in item and trade_direction in ["BOTH (CE & PE)", "ONLY CALL (CE)"]:
                ce_ltp = item['CE'].get('lastPrice', 0)
                ce_strike = item['CE'].get('strikePrice', 0)
                if 3.0 <= ce_ltp <= 5.0:
                    signals.append({
                        "Type": "CALL (CE)",
                        "Strike": ce_strike,
                        "Premium (₹)": ce_ltp,
                        "Max Risk": "₹250 - ₹300",
                        "Action": "BUY"
                    })
            
            # Check Put Option (PE)
            if 'PE' in item and trade_direction in ["BOTH (CE & PE)", "ONLY PUT (PE)"]:
                pe_ltp = item['PE'].get('lastPrice', 0)
                pe_strike = item['PE'].get('strikePrice', 0)
                if 3.0 <= pe_ltp <= 5.0:
                    signals.append({
                        "Type": "PUT (PE)",
                        "Strike": pe_strike,
                        "Premium (₹)": pe_ltp,
                        "Max Risk": "₹250 - ₹300",
                        "Action": "BUY"
                    })

        if len(signals) > 0:
            df_signals = pd.DataFrame(signals)
            st.table(df_signals)
        else:
            st.info("Is samay ₹3 se ₹5 ki range mein koi option match nahi ho raha hai.")
else:
    st.warning("⚠️ Market closed ya data restricted hai. Live market hours mein yeh automatically signals dikhayega.")

# --- AUTO-RUN LOGIC ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
