
import json
import os
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================================
# REAL DATA-DRIVEN BACKTEST ENGINE (NO MOCK / NO SYNTHETIC DUMMY)
# =============================================================================
def run_real_indicator_backtest(index_symbol, qty_multiplier=1, allowed_days=None, slippage_pct=0.002):
    if allowed_days is None:
        allowed_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    ticker_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
    ticker = ticker_map.get(index_symbol, "^NSEI")
    
    # Downloading Real 1-Year Historical Daily Candle Data
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # Calculate Real Technical Indicators (ATR & Volatility)
    df['TR'] = np.maximum(
        df['High'] - df['Low'],
        np.maximum(
            abs(df['High'] - df['Close'].shift(1)),
            abs(df['Low'] - df['Close'].shift(1))
        )
    )
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df.dropna(inplace=True)

    trades = []
    lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25}
    total_qty = lot_sizes.get(index_symbol, 15) * int(qty_multiplier)

    for idx, row in df.iterrows():
        day_name = idx.strftime("%A")
        if day_name not in allowed_days:
            continue

        trade_date = idx.strftime("%Y-%m-%d")
        open_p = float(row["Open"])
        high_p = float(row["High"])
        low_p = float(row["Low"])
        close_p = float(row["Close"])
        atr_val = float(row["ATR"])

        # Real Breakout Logic: Entry occurs ONLY if Market moves more than 0.5 * ATR
        breakout_threshold = 0.5 * atr_val

        if (high_p - open_p) >= breakout_threshold and close_p > open_p:
            # Bullish Breakout (CE Trade)
            entry_spot = open_p + breakout_threshold
            sl_spot = entry_spot - (0.4 * atr_val)  # Real Technical Stop Loss
            target_spot = entry_spot + (0.8 * atr_val) # 1:2 Risk-Reward Target
            leg = "CE"
        elif (open_p - low_p) >= breakout_threshold and close_p < open_p:
            # Bearish Breakout (PE Trade)
            entry_spot = open_p - breakout_threshold
            sl_spot = entry_spot + (0.4 * atr_val)
            target_spot = entry_spot - (0.8 * atr_val)
            leg = "PE"
        else:
            # No genuine technical pattern -> No Trade
            continue

        # Execution Status Based on Actual High/Low of the Day
        if leg == "CE":
            if high_p >= target_spot:
                exit_spot = target_spot
                status = "TARGET_PROFIT"
            elif low_p <= sl_spot:
                exit_spot = sl_spot
                status = "SL_HIT"
            else:
                exit_spot = close_p
                status = "EOD_EXIT"
        else:
            if low_p <= target_spot:
                exit_spot = target_spot
                status = "TARGET_PROFIT"
            elif high_p >= sl_spot:
                exit_spot = sl_spot
                status = "SL_HIT"
            else:
                exit_spot = close_p
                status = "EOD_EXIT"

        # Points PnL based on Real Spot Price Movement
        points_gained = (exit_spot - entry_spot) if leg == "CE" else (entry_spot - exit_spot)
        gross_pnl = points_gained * total_qty
        
        # Real Brokerage & Exchange Turnover Charges
        turnover = (entry_spot + exit_spot) * total_qty
        charges = round(min(40.0, turnover * 0.0005) + 15.0, 2)
        net_pnl = gross_pnl - charges

        trades.append({
            "Date": trade_date, "Day": day_name, "Index": index_symbol, "Leg": leg,
            "Entry Spot": round(entry_spot, 2), "Exit Spot": round(exit_spot, 2),
            "Points": round(points_gained, 2), "Gross PnL": round(gross_pnl, 2),
            "Taxes": charges, "Net PnL": round(net_pnl, 2), "Status": status
        })

    return pd.DataFrame(trades)
