import streamlit as st
import pandas as pd
import time
from nsepython import nse_optionchain_scrip

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Live Option Scanner",
    page_icon="📈",
    layout="wide"
)

# App Header
st.title("🚀 Zero-Hero Live Option Scanner (Real-Time)")
st.markdown("##### 100% Real Live NSE Data • Deep ITM/OTM Strike Tracking (₹3 - ₹5)")
st.markdown("---")

# --- TOP CONTROLS ---
top_col1, top_col2, top_col3 = st.columns(3)

with top_col1:
    selected_symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])

# Fetch Live Expiries from NSE
try:
    raw_data = nse_optionchain_scrip(selected_symbol)
    expiries = raw_data['records']['expiryDates']
except Exception:
    expiries = ["Current Weekly"]

with top_col2:
    selected_expiry = st.selectbox("Select Expiry", expiries)

with top_col3:
    st.markdown("### ") 
    auto_refresh = st.checkbox("🔄 Auto-Run Every 2 Seconds", value=False)

st.markdown("---")

# --- LIVE DATA FETCHING FUNCTION ---
def get_live_market_data(symbol, expiry):
    try:
        data = nse_optionchain_scrip(symbol)
        spot_price = data['records']['underlyingValue']
        records = data['records']['data']
        
        signals = []
        for item in records:
            if item.get('expiryDate') == expiry:
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
                        
        return spot_price, signals
    except Exception as e:
        return None, str(e)

# Fetching Data
spot, result = get_live_market_data(selected_symbol, selected_expiry)

if spot is not None:
    # Display Live Metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label=f"{selected_symbol} Live Spot Price", value=f"₹ {spot:,.2f}")
    with col2:
        st.metric(label="Active Selected Expiry", value=selected_expiry)

    st.markdown("---")
    st.subheader(f"🎯 Real Live Zero-Hero Signals (₹3 - ₹5)")

    if isinstance(result, list) and len(result) > 0:
        df_signals = pd.DataFrame(result)
        st.table(df_signals)
    else:
        st.info(f"Is samay selected expiry ({selected_expiry}) mein ₹3 se ₹5 ki range mein koi option active nahi hai. Market movement ke sath yahan live update hoga.")
else:
    st.warning(f"NSE server se data fetch nahi ho paya. (Error: {result}). Agar market band hai, toh live option chain data nahi dikhega.")

# --- AUTO-RUN LOGIC (2 Seconds interval) ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
