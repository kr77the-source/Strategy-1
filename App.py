import datetime
import yfinance as yf


def analyze_bias(ticker_symbol):
    print(f"\n==================================================")
    print(f"       ANALYZING LIVE BIAS FOR: {ticker_symbol.upper()}")
    print(f"==================================================\n")

    # Fetch daily data for Case 1 & Case 2
    ticker = yf.Ticker(ticker_symbol)
    df_daily = ticker.history(period="5d", interval="1d")

    if len(df_daily) < 2:
        print("Error: Live data fetch nahi ho paya. Ticker symbol re-check karein.")
        return

    # Previous Day Data (Index -2) & Current/Latest Day Data (Index -1)
    prev_day = df_daily.iloc[-2]
    curr_day = df_daily.iloc[-1]

    pdh = prev_day["High"]
    pdl = prev_day["Low"]
    pdc = prev_day["Close"]

    curr_high = curr_day["High"]
    curr_low = curr_day["Low"]
    curr_close = curr_day["Close"]

    range_size = pdh - pdl
    close_position = (pdc - pdl) / range_size if range_size > 0 else 0.5

    # -------------------------------------------------------------
    # CASE 1: Daily Closing Bias Logic
    # -------------------------------------------------------------
    case1_bias = "NEUTRAL"
    if close_position >= 0.70:
        case1_bias = "BULLISH (Strong High Close)"
    elif close_position <= 0.30:
        case1_bias = "BEARISH (Strong Low Close)"

    # -------------------------------------------------------------
    # CASE 2: Liquidity Sweep Logic (PDH/PDL)
    # -------------------------------------------------------------
    case2_bias = "NO SWEEP"
    # Buy-Side Liquidity (BSL) Sweep: Price went above PDH but closed below PDH
    if curr_high > pdh and curr_close < pdh:
        case2_bias = "BEARISH SWEEP (BSL Grabbed above PDH)"
    # Sell-Side Liquidity (SSL) Sweep: Price went below PDL but closed above PDL
    elif curr_low < pdl and curr_close > pdl:
        case2_bias = "BULLISH SWEEP (SSL Grabbed below PDL)"

    # -------------------------------------------------------------
    # CASE 3: Intra-session / Live Price Action Alignment
    # -------------------------------------------------------------
    # Fetch 15-minute intraday data
    df_15m = ticker.history(period="2d", interval="15m")
    current_price = curr_close

    if not df_15m.empty:
        current_price = df_15m.iloc[-1]["Close"]

    # Final Decision Matrix
    final_bias = "NEUTRAL / NO CLEAR DIRECTION"
    entry_price = 0.0
    stop_loss = 0.0
    target_1 = 0.0

    # Decision Rules
    if "BULLISH SWEEP" in case2_bias or (
        "BULLISH" in case1_bias and current_price > pdc
    ):
        final_bias = "BUY (LONG)"
        entry_price = round(current_price, 2)
        # SL below recent low / swept low
        stop_loss = round(min(curr_low, pdl) * 0.997, 2)
        # Risk to Reward 1:2
        risk = entry_price - stop_loss
        target_1 = round(entry_price + (risk * 2), 2)

    elif "BEARISH SWEEP" in case2_bias or (
        "BEARISH" in case1_bias and current_price < pdc
    ):
        final_bias = "SELL (SHORT)"
        entry_price = round(current_price, 2)
        # SL above recent high / swept high
        stop_loss = round(max(curr_high, pdh) * 1.003, 2)
        # Risk to Reward 1:2
        risk = stop_loss - entry_price
        target_1 = round(entry_price - (risk * 2), 2)

    # -------------------------------------------------------------
    # PRINT RESULTS
    # -------------------------------------------------------------
    print(f"Live Price        : {round(current_price, 2)}")
    print(f"Previous Day High : {round(pdh, 2)}")
    print(f"Previous Day Low  : {round(pdl, 2)}")
    print(f"Previous Day Close: {round(pdc, 2)}")
    print(f"--------------------------------------------------")
    print(f"[Case 1] Closing Bias   : {case1_bias}")
    print(f"[Case 2] Liquidity Sweep: {case2_bias}")
    print(f"--------------------------------------------------")
    print(f"FINAL SYSTEM BIAS       : >>> {final_bias} <<<")

    if final_bias in ["BUY (LONG)", "SELL (SHORT)"]:
        print(f"Suggested Entry Range   : {entry_price}")
        print(f"Calculated Stop Loss    : {stop_loss}")
        print(f"Target 1 (1:2 R:R)      : {target_1}")
    else:
        print("Market Rangebound / Liquidity Sweep ke confirmation ka wait karein.")

    print(f"==================================================\n")


if __name__ == "__main__":
    # Interface: User Input for Share Name
    print("Welcome to 3-Case Daily Bias System")
    user_symbol = input(
        "Enter Stock/Index Ticker (e.g., RELIANCE.NS, YESBANK.NS, IDEA.NS, ^NSEI): "
    )

    if user_symbol.strip():
        # Auto-append .NS for Indian Stocks if forgotten
        symbol = user_symbol.strip().upper()
        if not symbol.startswith("^") and not symbol.endswith(".NS"):
            symbol += ".NS"

        analyze_bias(symbol)
