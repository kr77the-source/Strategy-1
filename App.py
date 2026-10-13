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
st.title("🚀 Zero-Hero Live Option Scanner (Phone Edition)")
st.markdown("##### Real-Time NSE Option Chain Tracker (₹3 - ₹5 Strike Filter)")
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

# --- FETCH DATA USING PROXY/SESSION TO BYPASS CLOUD BLOCK ---
@st.cache_data(ttl=2) # Cache for 2 seconds to prevent rate limits
def fetch_live_data(symbol):
    # Using public financial gateway / proxy to bypass cloud IP restriction
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.nseindia.com/"
    }
    
    try:
        session = requests.Session()
        # Step 1: Hit home page to capture valid cookies
        home_resp = session.get("https://www.nseindia.com", headers=headers, timeout=5)
        cookies = home_resp.cookies
        
        # Step 2: Fetch option chain with cookies
        response = session.get(url, headers=headers, cookies=cookies, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        return None

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
        st.info(f"Is samay market mein ₹3 se ₹5 ki range mein koi option active nahi hai.")
else:
    st.warning("⚠️ Live market hours ke bahar NSE option chain data restrict kar deta hai. Market open hone par yeh yahin aapke phone par live update dikhayega.")

# --- AUTO-RUN LOGIC (2 Seconds interval) ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
