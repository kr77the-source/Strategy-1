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

# User Input Widget (Terminal input() ki jagah Streamlit input)
user_symbol = st.text_input(
    "Stock/Index Ticker Enter Karein:",
    value="RELIANCE.NS",
    help="Examples: RELIANCE.NS, YESBANK.NS, IDEA.NS, ^NSEI",
)

if st.button("Analyze Bias") or user_symbol:
    if user_symbol.strip():
        symbol = user_symbol.strip().upper()
        if not symbol.startswith("^") and not symbol.endswith(".NS"):
            symbol += ".NS"

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

                    # CASE 1
                    case1_bias = "NEUTRAL"
                    if close_position >= 0.70:
                        case1_bias = "BULLISH (Strong High Close)"
                    elif close_position <= 0.30:
                        case1_bias = "BEARISH (Strong Low Close)"

                    # CASE 2
                    case2_bias = "NO SWEEP"
                    if curr_high > pdh and curr_close < pdh:
                        case2_bias = "BEARISH SWEEP (BSL Grabbed above PDH)"
                    elif curr_low < pdl and curr_close > pdl:
                        case2_bias = "BULLISH SWEEP (SSL Grabbed below PDL)"

                    # CASE 3 & Final Calculation
                    df_15m = ticker.history(period="2d", interval="15m")
                    current_price = (
                        df_15m.iloc[-1]["Close"]
                        if not df_15m.empty
                        else curr_close
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

                    # Display Metrics
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
