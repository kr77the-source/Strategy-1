import datetime
import streamlit as st
from streamlit_searchbox import st_searchbox
import yfinance as yf

# Streamlit Page Config
st.set_page_config(
    page_title="3-Case Daily Bias System", page_icon="📈", layout="centered"
)

st.title("📈 3-Case Daily Bias System")
st.write(
    "Live stock data analyze karke Buy/Sell Bias, Stop Loss aur Targets dekhein."
)

# Popular Stocks & Indices List
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
    "^NSEI",
    "^NSEBANK",
]


# Live Filter Function for Auto-complete
def search_stocks(search_term: str):
    if not search_term:
        return []

    search_term = search_term.upper().strip()
    matches = [s for s in STOCK_DATABASE if search_term in s.upper()]

    # Agar list mein nah mile toh custom ticker suggestion
    if not matches and len(search_term) > 0:
        custom_symbol = (
            search_term
            if search_term.startswith("^") or search_term.endswith(".NS")
            else f"{search_term}.NS"
        )
        matches = [custom_symbol]

    return matches


# Dynamic Search Box (Type karte hi suggestions aayenge)
selected_symbol = st_searchbox(
    search_stocks,
    key="stock_search",
    placeholder="Stock name type karein (e.g. YES, RELIANCE, IDEA)...",
)

if selected_symbol:
    symbol = selected_symbol.upper()

    with st.spinner(f"Fetching live data for {symbol}..."):
        try:
            ticker = yf.Ticker(symbol)
            df_daily = ticker.history(period="5d", interval="1d")

            if len(df_daily) < 2:
                st.error(
                    "Error: Live data fetch nahi ho paya. Ticker symbol re-check karein."
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
