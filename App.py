import streamlit as st
import time

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Option Scanner",
    page_icon="📈",
    layout="wide"
)

# Custom Styling
st.markdown("""
    <style>
    .main {
        background-color: #070a16;
        color: rgba(255,255,255,0.88);
    }
    </style>
""", unsafe_allow_html=True)

# App Header
st.title("🚀 Zero-Hero Option Scanner")
st.markdown("##### Live Market F&O Scanner • Deep ITM/OTM Strike Tracking (₹3 - ₹5)")
st.markdown("---")

# --- TOP CONTROLS (Sidebar removed, moved to main page top) ---
top_col1, top_col2, top_col3 = st.columns(3)

with top_col1:
    selected_symbol = st.selectbox("Select Index / Stock", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])

with top_col2:
    selected_expiry = st.selectbox("Select Expiry", ["Current Weekly", "Next Weekly", "Monthly"])

with top_col3:
    st.markdown("### ") # Alignment spacing
    auto_refresh = st.checkbox("🔄 Auto-Run Every 2 Seconds", value=False)

st.markdown("---")

# Main Dashboard layout (Metrics)
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label=f"{selected_symbol} Spot Price", value="24,380.50", delta="+45.20")

with col2:
    st.metric(label="Day High", value="24,500.00")

with col3:
    st.metric(label="Day Low", value="24,200.00")

st.markdown("---")

# Results Section
st.subheader(f"🎯 Active Zero-Hero Signals for {selected_symbol} ({selected_expiry})")

data = {
    "Type": ["CALL", "PUT"],
    "Strike": [24600, 24100],
    "Premium (₹)": [3.50, 4.10],
    "Max Risk": ["₹250 - ₹300", "₹250 - ₹300"],
    "Action": ["BUY", "BUY"]
}
st.table(data)

# --- AUTO-RUN LOGIC (2 Seconds interval) ---
if auto_refresh:
    time.sleep(2)
    st.rerun()
