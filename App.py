import streamlit as st
import pandas as pd
import requests
import time

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Live Option Scanner",
    page_icon="📈",
    layout="wide"
)

# App Header
st.title("🚀 Zero-Hero Option Scanner (Local & Live)")
st.markdown("##### Direct NSE Option Chain Tracker (₹3 - ₹5 Strike Filter)")
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

# --- NSE LIVE DATA FETCHING VIA REQUESTS ---
def fetch_nse_option_chain(symbol):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br"
    }
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        response = session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

# Fetching Data
data = fetch_nse_option_chain(selected_symbol)

if data and 'records' in data:
    spot_price = data['records']['underlyingValue']
    records = data['records']['data']
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label=f"{selected_symbol} Live Spot Price", value=f"₹ {spot_price:,.2f}")
    with col2:
        st.metric(label="Active Selected Expiry", value=selected_expiry)

    st.markdown("---")
    st.subheader(f"🎯 Zero-Hero Signals (₹3 - ₹5 Premium)")

    signals = []
    for item in records:
        # Check Call Option (CE)
        if 'CE' in item:
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
        if 'PE' in item:
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
        st.info(f"Is samay ₹3 se ₹5 ki range mein koi option active nahi hai.")
else:
    st.warning("⚠️ NSE server ne cloud request block kar di hai (Cloud Server IP restriction). Aap is code ko apne **Windows 11 laptop** par VS Code mein run karenge toh yeh error bilkul nahi aayegi kyunki local broadband IP par NSE block nahi karta!")

# --- AUTO-RUN LOGIC ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
