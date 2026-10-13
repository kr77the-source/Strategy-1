import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="Zero-Hero Option Scanner",
    page_icon="📈",
    layout="wide"
)

# Custom Styling (CSS)
st.markdown("""
    <style>
    .main {
        background-color: #070a16;
        color: rgba(255,255,255,0.88);
    }
    .stButton>button {
        background: linear-gradient(135deg, rgba(255,122,24,0.8), rgba(181,107,255,0.8));
        color: white;
        border-radius: 12px;
        font-weight: bold;
        border: none;
    }
    </style>
""", unsafe_allow_html=True)

# App Header
st.title("🚀 Zero-Hero Option Scanner")
st.markdown("##### Live Market F&O Scanner • Deep ITM/OTM Strike Tracking (₹3 - ₹5)")

# Sidebar Controls
st.sidebar.header("Trading Controls")
selected_symbol = st.sidebar.selectbox("Select Index / Stock", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
selected_expiry = st.sidebar.selectbox("Select Expiry", ["Current Weekly", "Next Weekly", "Monthly"])

scan_button = st.sidebar.button("Run Live Scan")

# Main Dashboard layout
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Spot Price", value="24,380.50", delta="+45.20")

with col2:
    st.metric(label="Day High", value="24,500.00")

with col3:
    st.metric(label="Day Low", value="24,200.00")

st.markdown("---")

# Results Section
if scan_button:
    st.success(f"Scanning Live Option Chain for {selected_symbol} ({selected_expiry})...")
    
    # Placeholder table for Zero-Hero Signals
    st.subheader("🎯 Active Zero-Hero Signals (₹3 - ₹5 Premium)")
    
    data = {
        "Type": ["CALL", "PUT"],
        "Strike": [24600, 24100],
        "Premium (₹)": [3.50, 4.10],
        "Max Risk": ["₹262", "₹307"],
        "Action": ["BUY", "BUY"]
    }
    st.table(data)
else:
    st.info("Sidebar mein **'Run Live Scan'** button par click karein taaki signals load ho sakein.")
