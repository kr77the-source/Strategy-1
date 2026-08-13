import streamlit as st
import yfinance as yf
import pandas as pd

# -----------------------------------------------------------------------------
# PAGE CONFIGURATION
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Real-Time Strategy Dashboard", layout="wide")
st.title("🎯 Strategy Execution: Strategy Low, Entry, SL & Target")

# -----------------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
st.sidebar.header("Strategy Inputs")
symbol = st.sidebar.text_input("Enter NSE Stock Symbol (e.g., RELIANCE.NS, TATAMOTORS.NS)", value="RELIANCE.NS")
lookback_period = st.sidebar.selectbox("Lookback Data Period", ["1d", "5d", "1mo", "3mo"], index=1)
timeframe = st.sidebar.selectbox("Timeframe", ["5m", "15m", "60m", "1d"], index=1)

st.sidebar.subheader("Risk & Strategy Rules")
rr_ratio = st.sidebar.number_input("Risk-To-Reward Ratio (1:X)", min_value=1.0, value=2.0, step=0.5)
buffer_pct = st.sidebar.number_input("SL Buffer Below Strategy Low (%)", min_value=0.0, value=0.2, step=0.1)

# -----------------------------------------------------------------------------
# FETCH REAL DATA & CALCULATE STRATEGY
# -----------------------------------------------------------------------------
def execute_strategy(ticker_symbol, period, interval):
    # Fetch live/latest market data from Yahoo Finance
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period, interval=interval)
    
    if df.empty:
        return None, "No market data found for the given symbol."
    
    # Real Calculations based on recent candle strategy
    latest_candle = df.iloc[-1]
    previous_candles = df.iloc[-10:] # Look at last 10 candles for local low
    
    # Strategy Low: Lowest price point in the recent window
    strategy_low = float(previous_candles['Low'].min())
    
    # Real Entry: Current Market Price (Latest Close)
    entry_price = float(latest_candle['Close'])
    
    # Stop Loss: Strategy Low minus buffer %
    stop_loss = strategy_low * (1 - (buffer_pct / 100.0))
    
    # Risk per share
    risk = entry_price - stop_loss
    
    # Target Price based on Risk-Reward Ratio
    target_price = entry_price + (risk * rr_ratio)
    
    strategy_data = {
        "Symbol": ticker_symbol,
        "Current Entry": round(entry_price, 2),
        "Strategy Low": round(strategy_low, 2),
        "Stop Loss (SL)": round(stop_loss, 2),
        "Target Price": round(target_price, 2),
        "Risk Amount": round(risk, 2),
        "Reward Amount": round(risk * rr_ratio, 2)
    }
    
    return strategy_data, df

# -----------------------------------------------------------------------------
# MAIN APP EXECUTION
# -----------------------------------------------------------------------------
if st.button("Run Real Strategy Analysis", width="stretch"):
    with st.spinner("Fetching live market data..."):
        results, market_data = execute_strategy(symbol, lookback_period, timeframe)
        
        if results is None:
            st.error(market_data)
        else:
            # Display Real Strategy Metrics
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📌 Entry Price (CMP)", f"₹{results['Current Entry']}")
            c2.metric("📉 Strategy Low", f"₹{results['Strategy Low']}")
            c3.metric("🔴 Stop Loss (SL)", f"₹{results['Stop Loss (SL)']}")
            c4.metric("🟢 Target (TP)", f"₹{results['Target Price']}")
            
            st.divider()
            
            # Risk/Reward Summary
            st.subheader("📊 Trade Parameters")
            col_a, col_b = st.columns(2)
            col_a.info(f"**Risk per Share:** ₹{results['Risk Amount']}")
            col_b.success(f"**Expected Reward per Share:** ₹{results['Reward Amount']}")
            
            # Show Recent Live Market Data (Real OHLC)
            st.subheader("📈 Live Market Data (Last 10 Candles)")
            st.dataframe(market_data[['Open', 'High', 'Low', 'Close', 'Volume']].tail(10), width="stretch")
