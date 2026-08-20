# =============================================================================
# LIVE PROCESSOR ENGINE (WITH EOD CAP & CATCH-UP LOGIC)
# =============================================================================
def process_live(selected_stocks, tf_mins, fast_len, slow_len, atr_len, atr_mult, use_atr, trade_capital, leverage, slippage_bps):
    now = datetime.now(IST)
    data = fetch_market_data(selected_stocks, tf_mins)
    if data is None or (isinstance(data, dict) and not data):
        return

    buying_power = float(trade_capital) * float(leverage)
    db = load_db()

    if "processed_keys" not in st.session_state:
        st.session_state.processed_keys = set()

    for symbol in selected_stocks:
        try:
            df = data[symbol].dropna(how="all") if len(selected_stocks) > 1 else data
            if df is None or len(df) < slow_len + 2:
                continue

            ind = add_indicators(df, fast_len, slow_len, atr_len)
            symbol_clean = symbol.replace(".NS", "")

            # 1. Catch-up scan for historical candles of today (in case app was asleep)
            for i in range(slow_len + 1, len(ind)):
                candle_dt = ind.index[i]
                candle_key = f"{symbol}_{candle_dt.isoformat()}"
                c_time = candle_dt.time()

                norm_signal, rev_signal = signal_at(ind, i)
                atr_val = float(ind["ATR"].iloc[i])
                ltp = float(ind["Close"].iloc[i])

                # Process missed signals before 3:00 PM
                if candle_key not in st.session_state.processed_keys and c_time < dt_time(15, 0):
                    st.session_state.processed_keys.add(candle_key)

                    if norm_signal and db[(db["Symbol"] == symbol_clean) & (db["StrategyMode"] == "Normal") & (db["Status"] == "LIVE")].empty:
                        entry_p = apply_slippage(ltp, "BUY", slippage_bps)
                        qty = max(1, int(buying_power / max(entry_p, 0.01)))
                        sl_p = entry_p - (atr_mult * atr_val) if use_atr and not np.isnan(atr_val) else entry_p * 0.95
                        
                        upsert_trade_to_db({
                            "TradeID": f"N_{candle_dt.strftime('%Y%m%d%H%M')}_{symbol_clean}",
                            "Date": candle_dt.strftime("%Y-%m-%d"),
                            "EntryTime": candle_dt.strftime("%H:%M:%S"),
                            "ExitTime": "-",
                            "Symbol": symbol_clean,
                            "StrategyMode": "Normal",
                            "Type": "BUY",
                            "Qty": qty,
                            "EntryPrice": round(entry_p, 2),
                            "CurrentPrice": round(entry_p, 2),
                            "ExitPrice": "-",
                            "SL": round(sl_p, 2),
                            "Status": "LIVE",
                            "GrossPnL": 0.0,
                            "Charges": 0.0,
                            "NetPnL": 0.0,
                            "EntryReason": "EMA_CROSSOVER_BUY",
                            "ExitReason": "-"
                        })

            # 2. Manage Active Positions & EOD Closure
            active_trades = db[(db["Symbol"] == symbol_clean) & (db["Status"] == "LIVE")]
            latest_ltp = float(ind["Close"].iloc[-1])

            for _, row in active_trades.iterrows():
                side = row["Type"]
                entry_p = float(row["EntryPrice"])
                qty = int(row["Qty"])
                sl_p = float(row["SL"])

                gross = (latest_ltp - entry_p) * qty if side == "BUY" else (entry_p - latest_ltp) * qty
                charges = estimate_charges(entry_p, latest_ltp, qty)
                updated = dict(row)
                updated["CurrentPrice"] = round(latest_ltp, 2)
                updated["GrossPnL"] = round(gross, 2)
                updated["Charges"] = round(charges, 2)
                updated["NetPnL"] = round(gross - charges, 2)

                hit_sl = (side == "BUY" and latest_ltp <= sl_p) or (side == "SELL" and latest_ltp >= sl_p)
                is_eod = should_squareoff(now)

                if hit_sl or is_eod:
                    exit_p = apply_slippage(latest_ltp, "SELL" if side == "BUY" else "BUY", slippage_bps)
                    gross_final = (exit_p - entry_p) * qty if side == "BUY" else (entry_p - exit_p) * qty
                    charges_final = estimate_charges(entry_p, exit_p, qty)

                    reason = "SL_HIT" if hit_sl else "EOD_SQUAREOFF"
                    
                    # Capping Exit Time strictly to 15:25:00 if closed after market hours
                    exit_time_str = "15:25:00" if (is_eod and now.time() >= dt_time(15, 25)) else now.strftime("%H:%M:%S")

                    updated.update({
                        "ExitPrice": round(exit_p, 2),
                        "ExitTime": exit_time_str,
                        "Status": f"CLOSED ({reason})",
                        "GrossPnL": round(gross_final, 2),
                        "Charges": charges_final,
                        "NetPnL": round(gross_final - charges_final, 2),
                        "ExitReason": reason
                    })
                upsert_trade_to_db(updated)

        except Exception:
            continue
