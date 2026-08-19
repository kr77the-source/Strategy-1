# =============================================================================
# BACKTEST ENGINE (60 DAYS) - STRICT INTRADAY NO-CARRYOVER
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def run_60d_backtest(stocks_list, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_val, leverage, tf_mins, slippage_bps):
    tf_str = "1h" if tf_mins == 60 else f"{tf_mins}m"
    try:
        data = yf.download(tickers=" ".join(stocks_list), period="60d", interval=tf_str, group_by="ticker", threads=True, progress=False)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    norm_list, rev_list = [], []
    buying_power = float(trade_val) * float(leverage)

    for symbol in stocks_list:
        try:
            df = data[symbol].dropna(how="all") if len(stocks_list) > 1 else data
            if df is None or len(df) < slow_len + 10:
                continue

            df = add_indicators(df, fast_len, slow_len, atr_len)

            for mode, side, out_list in [("Normal", "BUY", norm_list), ("Reversal", "SELL", rev_list)]:
                open_trade = None
                for i in range(slow_len + 1, len(df) - 1):
                    current_dt = df.index[i]
                    next_dt = df.index[i + 1]
                    c_time = current_dt.time()
                    
                    # Check if today is the last candle of the trading day
                    is_last_candle_of_day = (next_dt.date() != current_dt.date()) or (c_time >= dt_time(15, 15))

                    if open_trade is not None:
                        hi, lo, close = float(df["High"].iloc[i]), float(df["Low"].iloc[i]), float(df["Close"].iloc[i])
                        ts = current_dt
                        exit_price, reason = None, None

                        # 1. Check ATR Stop Loss
                        if side == "BUY" and use_atr and lo <= open_trade["SL"]:
                            exit_price, reason = open_trade["SL"], "ATR_SL"
                        elif side == "SELL" and use_atr and hi >= open_trade["SL"]:
                            exit_price, reason = open_trade["SL"], "ATR_SL"
                        
                        # 2. Strict Intraday EOD Square-off (Closing on same day)
                        elif is_last_candle_of_day:
                            exit_price = apply_slippage(close, "SELL" if side == "BUY" else "BUY", slippage_bps)
                            reason = "EOD_SQUAREOFF"

                        # 3. Check Opposite Signal
                        else:
                            ns, rs = signal_at(df, i)
                            if (side == "BUY" and rs) or (side == "SELL" and ns):
                                exit_price = apply_slippage(float(df["Open"].iloc[i + 1]), "SELL" if side == "BUY" else "BUY", slippage_bps)
                                reason = "OPPOSITE_SIGNAL"
                                ts = df.index[i + 1]

                        # Process Trade Closure
                        if exit_price is not None:
                            entry, qty = open_trade["EntryPrice"], open_trade["Qty"]
                            gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                            chg = estimate_charges(entry, exit_price, qty)
                            out_list.append({
                                "Date": open_trade["Date"], 
                                "EntryTime": open_trade["EntryTime"], 
                                "ExitTime": ts.strftime("%H:%M"),
                                "Symbol": symbol.replace(".NS", ""), 
                                "Type": side, 
                                "Qty": qty,
                                "EntryPrice": round(entry, 2), 
                                "ExitPrice": round(exit_price, 2), 
                                "SL": round(open_trade["SL"], 2),
                                "GrossPnL": round(gross, 2), 
                                "Charges": chg, 
                                "NetPnL": round(gross - chg, 2), 
                                "ExitReason": reason
                            })
                            open_trade = None
                            continue

                    # Trigger New Intraday Entry (Strictly before 3:00 PM and not on last candle)
                    if c_time < dt_time(15, 0) and not is_last_candle_of_day:
                        ns, rs = signal_at(df, i)
                        trigger = ns if side == "BUY" else rs
                        if trigger and open_trade is None and i + 1 < len(df):
                            entry_raw = float(df["Open"].iloc[i + 1])
                            entry = apply_slippage(entry_raw, side, slippage_bps)
                            atr = float(df["ATR"].iloc[i])
                            sl = (entry - atr_mult * atr) if side == "BUY" else (entry + atr_mult * atr)
                            qty = max(1, int(buying_power / max(entry, 0.01)))
                            open_trade = {
                                "Date": df.index[i + 1].strftime("%Y-%m-%d"), 
                                "EntryTime": df.index[i + 1].strftime("%H:%M"), 
                                "EntryPrice": entry, 
                                "SL": sl, 
                                "Qty": qty
                            }

        except Exception:
            continue

    norm, rev = pd.DataFrame(norm_list), pd.DataFrame(rev_list)
    if not norm.empty: norm.insert(0, "Sr", range(1, len(norm) + 1))
    if not rev.empty: rev.insert(0, "Sr", range(1, len(rev) + 1))
    return norm, rev
