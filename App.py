def analyze_pullback_strategy(df):
    """3-Candle Opening Range Pullback + Low Volume Strategy with Target & SL."""
    if df is None or len(df) < 4:
        return {
            "status": "Insufficient Candles",
            "signal": "NONE",
            "trigger": 0.0,
            "sl": 0.0,
            "target": 0.0,
            "details": "Minimum 4 candles (5-min) needed for setup.",
        }

    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

    c1_green = closes[0] > opens[0]
    c2_green = closes[1] > opens[1]
    c3_green = closes[2] > opens[2]

    c1_red = closes[0] < opens[0]
    c2_red = closes[1] < opens[1]
    c3_red = closes[2] < opens[2]

    initial_3_avg_vol = np.mean(volumes[:3])

    for i in range(3, len(df)):
        curr_open = opens[i]
        curr_close = closes[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_vol = volumes[i]

        # 1. BUY SETUP LOGIC
        if c1_green and c2_green and c3_green:
            is_pullback_red = curr_close < curr_open
            if is_pullback_red and curr_vol < initial_3_avg_vol:
                entry_trigger = curr_high  # High break entry
                stop_loss = curr_low  # Low SL
                risk = entry_trigger - stop_loss
                target = (
                    entry_trigger + (risk * 2)
                )  # 1:2 Risk-Reward Exit Target

                latest_price = closes[-1]
                is_active = latest_price > entry_trigger

                return {
                    "status": "ACTIVE BUY SIGNAL"
                    if is_active
                    else "BUY SETUP FORMED",
                    "signal": "BUY",
                    "trigger": round(entry_trigger, 2),
                    "sl": round(stop_loss, 2),
                    "target": round(target, 2),  # Target Price Added
                    "details": f"3 Green + Low Vol Red Pullback. (Target: 1:2 R:R)",
                }

        # 2. SELL SETUP LOGIC
        if c1_red and c2_red and c3_red:
            is_pullback_green = curr_close > curr_open
            if is_pullback_green and curr_vol < initial_3_avg_vol:
                entry_trigger = curr_low  # Low break entry
                stop_loss = curr_high  # High SL
                risk = stop_loss - entry_trigger
                target = (
                    entry_trigger - (risk * 2)
                )  # 1:2 Risk-Reward Exit Target

                latest_price = closes[-1]
                is_active = latest_price < entry_trigger

                return {
                    "status": "ACTIVE SELL SIGNAL"
                    if is_active
                    else "SELL SETUP FORMED",
                    "signal": "SELL",
                    "trigger": round(entry_trigger, 2),
                    "sl": round(stop_loss, 2),
                    "target": round(target, 2),  # Target Price Added
                    "details": f"3 Red + Low Vol Green Pullback. (Target: 1:2 R:R)",
                }

    return {
        "status": "No Pattern Met",
        "signal": "NONE",
        "trigger": 0.0,
        "sl": 0.0,
        "target": 0.0,
        "details": "Opening pattern condition not satisfied.",
    }
