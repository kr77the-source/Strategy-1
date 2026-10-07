import datetime
import streamlit as st
import yfinance as yf

# Streamlit Page Config
st.set_page_config(
    page_title="3-Case Daily Bias System", page_icon="📈", layout="centered"
)

st.title("📈 3-Case Daily Bias System")
st.write(
    "Live stock data analyze karke Buy/Sell Bias, Stop Loss aur Targets dekhein."
)

# Popular Stocks & Indices List for Auto-complete / Recommendations
STOCK_DATABASE = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "SBIN.NS",
    "LTIM.NS",
    "LT.NS",
    "BAJFINANCE.NS",
    "HINDUNILVR.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TATASTEEL.NS",
    "TATAMOTORS.NS",
    "YESBANK.NS",
    "IDEA.NS",
    "AXISBANK.NS",
    "KOTAKBANK.NS",
    "M&M.NS",
    "NTPC.NS",
    "ONGC.NS",
    "POWERGRID.NS",
    "TITAN.NS",
    "ADANIENT.NS",
    "ADANIPORTS.NS",
    "ULTRACEMCO.NS",
    "COALINDIA.NS",
    "ASIANPAINT.NS",
    "WIPRO.NS",
    "HCLTECH.NS",
    "BAJAJ-AUTO.NS",
    "HEROMOTOCO.NS",
    "EICHERMOT.NS",
    "DIVISLAB.NS",
    "DRREDDY.NS",
    "CIPLA.NS",
    "BPCL.NS",
    "IOC.NS",
    "GRASIM.NS",
    "TECHM.NS",
    "JSWSTEEL.NS",
    "HDFCLIFE.NS",
    "SBILIFE.NS",
    "BEL.NS",
    "HAL.NS",
    "TATA-CHAIN.NS",
    "^NSEI",  # Nifty 50 Index
    "^NSEBANK",  # Nifty Bank Index
]

# Text input for filtering/typing
search_text = st.text_input(
    "Stock Name / Ticker Type Karein (e.g. YES, RELIANCE, IDEA):",
    value="RELIANCE",
)

# Filter recommendations based on starting letters
filtered_stocks = [
    s
    for s in STOCK_DATABASE
    if s.upper().startswith(search_text.strip().upper())
]

# If typing doesn't match default list, allow user's custom ticker
if not filtered_stocks and search_text.strip():
    custom_ticker = search_text.strip().upper()
    if not custom_ticker.startswith("^") and not custom_ticker.endswith(".NS"):
        custom_ticker += ".NS"
    filtered_stocks = [custom_ticker]

# Dropdown / Selectbox for Recommendation Selection
selected_symbol = st.selectbox(
    "Select Recommended Stock:",
    options=filtered_stocks
    if filtered_stocks
    else [search_text.strip().upper() + ".NS"],
)

if st.button("Analyze Bias") and selected_symbol:
    symbol = selected_symbol

    with st.spinner(f"Fetching live data for {symbol}..."):
        try:
            ticker = yf.Ticker(symbol)
            df_daily = ticker.history(period="5d", interval="1d")

            if len(df_daily) < 2:
                st.error(
                    "Error: Live data fetch nahi ho paya. Ticker symbol check karein."
                )
            else:
                prev_day = df_daily.iloc[-2]
                curr_day = df_daily.iloc[-1]

                pdh = prev_day["High"]
                pdl = prev_day["Low"]
                pdc = prev_day["Close"]

                curr_high = curr_day["High"]
                curr_low = curr_day["Low"]
                curr_close = curr_day["Close"]

                range_size = pdh - pdl
                close_position = (
                    (pdc - pdl) / range_size if range_size > 0 else 0.5
                )

                # CASE 1: Daily Closing Bias
                case1_bias = "NEUTRAL"
                if close_position >= 0.70:
                    case1_bias = "BULLISH (Strong High Close)"
                elif close_position <= 0.30:
                    case1_bias = "BEARISH (Strong Low Close)"

                # CASE 2: Liquidity Sweep
                case2_bias = "NO SWEEP"
                if curr_high > pdh and curr_close < pdh:
                    case2_bias = "BEARISH SWEEP (BSL Grabbed above PDH)"
                elif curr_low < pdl and curr_close > pdl:
                    case2_bias = "BULLISH SWEEP (SSL Grabbed below PDL)"

                # CASE 3 & Final Decision
                df_15m = ticker.history(period="2d", interval="15m")
                current_price = (
                    df_15m.iloc[-1]["Close"] if not df_15m.empty else curr_close
                )

                final_bias = "NEUTRAL / NO CLEAR DIRECTION"
                entry_price = 0.0
                stop_loss = 0.0
                target_1 = 0.0

                if "BULLISH SWEEP" in case2_bias or (
                    "BULLISH" in case1_bias and current_price > pdc
                ):
                    final_bias = "BUY (LONG)"
                    entry_price = round(current_price, 2)
                    stop_loss = round(min(curr_low, pdl) * 0.997, 2)
                    risk = entry_price - stop_loss
                    target_1 = round(entry_price + (risk * 2), 2)

                elif "BEARISH SWEEP" in case2_bias or (
                    "BEARISH" in case1_bias and current_price < pdc
                ):
                    final_bias = "SELL (SHORT)"
                    entry_price = round(current_price, 2)
                    stop_loss = round(max(curr_high, pdh) * 1.003, 2)
                    risk = stop_loss - entry_price
                    target_1 = round(entry_price - (risk * 2), 2)

                # Display Results
                st.subheader(f"Results for: {symbol}")

                col1, col2, col3 = st.columns(3)
                col1.metric("Live Price", f"₹{round(current_price, 2)}")
                col2.metric("PDH (High)", f"₹{round(pdh, 2)}")
                col3.metric("PDL (Low)", f"₹{round(pdl, 2)}")

                st.markdown("---")
                st.write(f"**[Case 1] Closing Bias:** {case1_bias}")
                st.write(f"**[Case 2] Liquidity Sweep:** {case2_bias}")
                st.markdown("---")

                if final_bias == "BUY (LONG)":
                    st.success(f"### FINAL BIAS: {final_bias}")
                elif final_bias == "SELL (SHORT)":
                    st.error(f"### FINAL BIAS: {final_bias}")
                else:
                    st.warning(f"### FINAL BIAS: {final_bias}")

                if final_bias in ["BUY (LONG)", "SELL (SHORT)"]:
                    res_col1, res_col2, res_col3 = st.columns(3)
                    res_col1.metric("Entry Price", f"₹{entry_price}")
                    res_col2.metric("Stop Loss", f"₹{stop_loss}")
                    res_col3.metric("Target (1:2 R:R)", f"₹{target_1}")
        except Exception as e:
            st.error(f"Error processing data: {e}")
