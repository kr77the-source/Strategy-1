import os
import time
import uuid
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    from growwapi import GrowwAPI
except Exception:
    GrowwAPI = None


# =============================================================================
# PAGE CONFIG & STYLES â€” dashboard kept in the same 3-tab structure
# =============================================================================
st.set_page_config(page_title="EMA Live Terminal & Backtest", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 2rem !important; padding-bottom: 0rem !important; padding-left: 1rem !important; padding-right: 1rem !important; }
header[data-testid="stHeader"] { background: transparent; }
.top-pnl-card {
    background: linear-gradient(135deg, #1e2530 0%, #161b22 100%);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 15px;
    color: #ffffff;
}
.metric-val-green { color: #4CAF50; font-weight: bold; font-size: 18px; }
.metric-val-red { color: #FF5252; font-weight: bold; font-size: 18px; }
</style>
""", unsafe_allow_html=True)

IST = ZoneInfo("Asia/Kolkata")
RUPEE = "&#8377;"

DEFAULT_STOCKS = [
    "YESBANK.NS", "PCJEWELLER.NS", "UJJIVANSFB.NS", "SOUTHBANK.NS",
    "BANDHANBNK.NS", "NMDC.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS"
]

HISTORY_FILE = "strategy_history_db.csv"
HISTORY_COLUMNS = [
    "TradeID", "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "StrategyMode",
    "Type", "Qty", "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status",
    "GrossPnL", "Charges", "NetPnL", "GrowwEntryOrderID", "GrowwSLOrderID",
    "GrowwExitOrderID", "EntryOrderStatus", "SLOrderStatus", "ExitOrderStatus",
    "EntryReason", "ExitReason"
]


# =============================================================================
# STORAGE
# =============================================================================
def load_db():
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE)
            for col in HISTORY_COLUMNS:
                if col not in df.columns:
                    df[col] = "-"
            return df[HISTORY_COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def save_db(df):
    df.to_csv(HISTORY_FILE, index=False)


def upsert_trade_to_db(trade_data: dict):
    df = load_db()
    tid = str(trade_data["TradeID"])
    if not df.empty and tid in df["TradeID"].astype(str).values:
        idx = df.index[df["TradeID"].astype(str) == tid][0]
        for key, val in trade_data.items():
            if key in df.columns:
                df.at[idx, key] = val
    else:
        trade_data = {c: trade_data.get(c, "-") for c in HISTORY_COLUMNS}
        trade_data["Sr"] = len(df) + 1
        df = pd.concat([df, pd.DataFrame([trade_data])], ignore_index=True)
    save_db(df)


# =============================================================================
# INDICATORS / STRATEGY â€” one shared engine for live + backtest
# =============================================================================
def calculate_ema(series, period):
    return series.ewm(span=int(period), adjust=False).mean()


def calculate_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def add_indicators(df, fast_len, slow_len, atr_len):
    out = df.copy()
    out["FastEMA"] = calculate_ema(out["Close"], fast_len)
    out["SlowEMA"] = calculate_ema(out["Close"], slow_len)
    out["ATR"] = calculate_atr(out, atr_len)
    return out


def signal_at(df, i):
    if i <= 0:
        return False, False
    fp, sp = float(df["FastEMA"].iloc[i - 1]), float(df["SlowEMA"].iloc[i - 1])
    fc, sc = float(df["FastEMA"].iloc[i]), float(df["SlowEMA"].iloc[i])
    if any(np.isnan(x) for x in (fp, sp, fc, sc)):
        return False, False
    return (fp <= sp and fc > sc), (fp >= sp and fc < sc)


# =============================================================================
# CHARGES / EXECUTION MODEL
# =============================================================================
def estimate_charges(entry_price, exit_price, qty):
    # Existing dashboard's charge model retained, but used consistently in
    # backtest and P&L display. Actual Groww contract-note charges remain the
    # authoritative real-trade figure.
    buy_turnover = float(entry_price) * int(qty)
    sell_turnover = float(exit_price) * int(qty)
    total_turnover = buy_turnover + sell_turnover
    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00025
    exchange_charges = total_turnover * 0.0000297
    gst = (brokerage + exchange_charges) * 0.18
    stamp_duty = buy_turnover * 0.00003
    sebi_charges = total_turnover * 0.000001
    return round(brokerage + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)


def apply_slippage(price, side, bps):
    p = float(price)
    b = float(bps) / 10000.0
    # Buy pays up; sell receives less.
    return p * (1 + b) if side == "BUY" else p * (1 - b)


# =============================================================================
# GROWw CONNECTION
# =============================================================================
@st.cache_resource(show_spinner=False)
def get_groww_client(access_token):
    if GrowwAPI is None:
        return None
    return GrowwAPI(access_token)


def get_secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def groww_symbol_from_nse(symbol):
    return symbol.replace(".NS", "").strip().upper()


def normalize_response(resp):
    if not isinstance(resp, dict):
        return {}
    payload = resp.get("payload")
    return payload if isinstance(payload, dict) else resp


def groww_ltp(groww, trading_symbol):
    resp = groww.get_ltp(
        segment=groww.SEGMENT_CASH,
        exchange_trading_symbols=f"NSE_{trading_symbol}"
    )
    payload = normalize_response(resp)
    if f"NSE_{trading_symbol}" in payload:
        return float(payload[f"NSE_{trading_symbol}"])
    if "ltp" in payload:
        return float(payload["ltp"])
    raise RuntimeError(f"Groww LTP response unexpected: {resp}")


def groww_place_market(groww, symbol, qty, transaction_type, reference_id):
    return groww.place_order(
        trading_symbol=symbol,
        quantity=int(qty),
        validity=groww.VALIDITY_DAY,
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_CASH,
        product=groww.PRODUCT_MIS,
        order_type=groww.ORDER_TYPE_MARKET,
        transaction_type=transaction_type,
        order_reference_id=reference_id,
    )


def groww_place_slm(groww, symbol, qty, transaction_type, trigger_price, reference_id):
    return groww.place_order(
        trading_symbol=symbol,
        quantity=int(qty),
        validity=groww.VALIDITY_DAY,
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_CASH,
        product=groww.PRODUCT_MIS,
        order_type=groww.ORDER_TYPE_STOP_LOSS_MARKET,
        transaction_type=transaction_type,
        trigger_price=float(trigger_price),
        order_reference_id=reference_id,
    )


def groww_order_status(groww, order_id):
    try:
        resp = groww.get_order_status(
            groww_order_id=str(order_id),
            segment=groww.SEGMENT_CASH
        )
        return normalize_response(resp)
    except Exception:
        return {}


def groww_order_detail(groww, order_id):
    try:
        resp = groww.get_order_detail(
            groww_order_id=str(order_id),
            segment=groww.SEGMENT_CASH
        )
        return normalize_response(resp)
    except Exception:
        return {}


def groww_cancel(groww, order_id):
    return groww.cancel_order(
        segment=groww.SEGMENT_CASH,
        groww_order_id=str(order_id)
    )


def extract_fill(order_detail):
    if not order_detail:
        return 0, None, ""
    qty = int(order_detail.get("filled_quantity") or 0)
    avg = order_detail.get("average_fill_price")
    if avg is None:
        # Some responses expose price rather than average_fill_price.
        avg = order_detail.get("price")
    status = str(order_detail.get("order_status", ""))
    return qty, (float(avg) if avg not in (None, "", "-") else None), status


# =============================================================================
# REAL GROWw HISTORICAL DATA
# =============================================================================
def groww_interval_constant(groww, tf_mins):
    mapping = {
        5: getattr(groww, "CANDLE_INTERVAL_MIN_5", None),
        15: getattr(groww, "CANDLE_INTERVAL_MIN_15", None),
        30: getattr(groww, "CANDLE_INTERVAL_MIN_30", None),
        60: getattr(groww, "CANDLE_INTERVAL_MIN_60", None),
    }
    return mapping[tf_mins]


def candles_to_df(resp):
    payload = normalize_response(resp)
    candles = payload.get("candles", [])
    rows = []
    for c in candles:
        if len(c) >= 6:
            rows.append([c[0], c[1], c[2], c[3], c[4], c[5]])
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(rows, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
    # Groww historical timestamps are epoch seconds in the documented response.
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="s", utc=True).dt.tz_convert(IST)
    df = df.set_index("Timestamp").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()


def fetch_groww_history(groww, symbol, tf_mins, days=5):
    now = datetime.now(IST)
    start = now - timedelta(days=days)
    resp = groww.get_historical_candles(
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_CASH,
        groww_symbol=f"NSE-{symbol}",
        start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
        end_time=now.strftime("%Y-%m-%d %H:%M:%S"),
        candle_interval=groww_interval_constant(groww, tf_mins),
    )
    return candles_to_df(resp)


def only_closed_candles(df, tf_mins, now=None):
    if df.empty:
        return df
    now = now or datetime.now(IST)
    out = df.copy()
    end_times = out.index + pd.Timedelta(minutes=int(tf_mins))
    return out[end_times <= pd.Timestamp(now)]


# =============================================================================
# LIVE ENGINE
# =============================================================================
def market_open_now(now):
    t = now.time()
    return dt_time(9, 15) <= t < dt_time(15, 30) and now.weekday() < 5


def should_squareoff(now):
    return now.time() >= dt_time(15, 25)


def next_ref(prefix):
    return f"{prefix}{uuid.uuid4().hex[:14]}"[:20]


def find_live_row(db, symbol, mode):
    if db.empty:
        return None
    x = db[
        (db["Symbol"] == symbol) &
        (db["StrategyMode"] == mode) &
        (db["Status"].isin(["LIVE", "ENTRY_PENDING", "SL_PENDING"]))
    ]
    return None if x.empty else x.iloc[0]


def create_live_entry(groww, symbol, mode, side, signal_close, atr,
                      atr_mult, trade_capital, leverage, use_atr, slippage_bps,
                      live_trading):
    ltp = groww_ltp(groww, symbol)
    entry_reference = next_ref("N" if mode == "Normal" else "R")
    entry_order_id = "-"
    entry_status = "PAPER_LIVE"

    # Quantity is based on configured notional buying power, but Groww is the
    # final authority for available margin/order acceptance.
    buying_power = float(trade_capital) * float(leverage)
    qty = max(1, int(buying_power / max(ltp, 0.01)))

    if live_trading:
        trans = groww.TRANSACTION_TYPE_BUY if side == "BUY" else groww.TRANSACTION_TYPE_SELL
        resp = groww_place_market(groww, symbol, qty, trans, entry_reference)
        payload = normalize_response(resp)
        if str(resp.get("status", "")).upper() != "SUCCESS" or not payload.get("groww_order_id"):
            raise RuntimeError(f"Groww entry rejected: {resp}")
        entry_order_id = payload["groww_order_id"]
        entry_status = payload.get("order_status", "OPEN")

        # Poll briefly for the actual fill; do NOT invent the entry price.
        fill_qty, fill_price, status = 0, None, entry_status
        for _ in range(10):
            detail = groww_order_detail(groww, entry_order_id)
            fill_qty, fill_price, status = extract_fill(detail)
            if fill_qty > 0 and fill_price is not None:
                break
            time.sleep(0.5)
        if fill_qty <= 0 or fill_price is None:
            raise RuntimeError(f"Entry order not filled yet. Groww status={status}")
        qty = fill_qty
        entry_price = fill_price
        entry_status = status
    else:
        entry_price = apply_slippage(ltp, side, slippage_bps)

    if use_atr and not np.isnan(atr) and atr > 0:
        sl = entry_price - atr_mult * atr if side == "BUY" else entry_price + atr_mult * atr
    else:
        sl = entry_price * 0.95 if side == "BUY" else entry_price * 1.05

    sl_order_id = "-"
    sl_status = "NOT_PLACED"

    # Real protection is a Groww SLM order. If it cannot be placed, do not
    # pretend that the position is protected.
    if live_trading:
        sl_trans = groww.TRANSACTION_TYPE_SELL if side == "BUY" else groww.TRANSACTION_TYPE_BUY
        sl_ref = next_ref("S" + ("N" if mode == "Normal" else "R"))
        sl_resp = groww_place_slm(
            groww, symbol, qty, sl_trans, round(sl, 2), sl_ref
        )
        sl_payload = normalize_response(sl_resp)
        if str(sl_resp.get("status", "")).upper() != "SUCCESS" or not sl_payload.get("groww_order_id"):
            # Immediately flatten if the protection order could not be created.
            exit_trans = groww.TRANSACTION_TYPE_SELL if side == "BUY" else groww.TRANSACTION_TYPE_BUY
            exit_ref = next_ref("X")
            try:
                groww_place_market(groww, symbol, qty, exit_trans, exit_ref)
            finally:
                raise RuntimeError(f"SL protection rejected; position flattened. Response={sl_resp}")
        sl_order_id = sl_payload["groww_order_id"]
        sl_status = sl_payload.get("order_status", "OPEN")

    now = datetime.now(IST)
    tid = f"{mode[:1].upper()}_{now.strftime('%Y%m%d%H%M%S')}_{symbol}"
    return {
        "TradeID": tid,
        "Date": now.strftime("%Y-%m-%d"),
        "EntryTime": now.strftime("%H:%M:%S"),
        "ExitTime": "-",
        "Symbol": symbol,
        "StrategyMode": mode,
        "Type": side,
        "Qty": qty,
        "EntryPrice": round(entry_price, 2),
        "CurrentPrice": round(ltp, 2),
        "ExitPrice": "-",
        "SL": round(sl, 2),
        "Status": "LIVE",
        "GrossPnL": 0.0,
        "Charges": 0.0,
        "NetPnL": 0.0,
        "GrowwEntryOrderID": entry_order_id,
        "GrowwSLOrderID": sl_order_id,
        "GrowwExitOrderID": "-",
        "EntryOrderStatus": entry_status,
        "SLOrderStatus": sl_status,
        "ExitOrderStatus": "-",
        "EntryReason": "CONFIRMED_CANDLE_CROSSOVER",
        "ExitReason": "-",
    }


def close_live_trade(groww, row, exit_reason, live_trading, ltp, slippage_bps):
    symbol = str(row["Symbol"])
    side = str(row["Type"])
    qty = int(row["Qty"])
    entry = float(row["EntryPrice"])
    sl_order_id = str(row.get("GrowwSLOrderID", "-"))

    exit_order_id = "-"
    exit_status = "PAPER_CLOSED"
    exit_price = apply_slippage(ltp, "SELL" if side == "BUY" else "BUY", slippage_bps)

    if live_trading:
        # Cancel protection before manual market exit. The SL is still the
        # primary protection; this path is for opposite signal/EOD/manual exit.
        if sl_order_id not in ("", "-", "nan"):
            try:
                groww_cancel(groww, sl_order_id)
            except Exception:
                pass

        trans = groww.TRANSACTION_TYPE_SELL if side == "BUY" else groww.TRANSACTION_TYPE_BUY
        ref = next_ref("X")
        resp = groww_place_market(groww, symbol, qty, trans, ref)
        payload = normalize_response(resp)
        if str(resp.get("status", "")).upper() != "SUCCESS" or not payload.get("groww_order_id"):
            raise RuntimeError(f"Groww exit rejected: {resp}")
        exit_order_id = payload["groww_order_id"]
        exit_status = payload.get("order_status", "OPEN")

        fill_qty, fill_price, status = 0, None, exit_status
        for _ in range(10):
            detail = groww_order_detail(groww, exit_order_id)
            fill_qty, fill_price, status = extract_fill(detail)
            if fill_qty > 0 and fill_price is not None:
                break
            time.sleep(0.5)
        if fill_qty > 0 and fill_price is not None:
            exit_price = fill_price
        exit_status = status

    gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
    charges = estimate_charges(entry, exit_price, qty)
    now = datetime.now(IST)

    updated = dict(row)
    updated.update({
        "CurrentPrice": round(exit_price, 2),
        "ExitPrice": round(exit_price, 2),
        "ExitTime": now.strftime("%H:%M:%S"),
        "Status": "CLOSED",
        "GrossPnL": round(gross, 2),
        "Charges": round(charges, 2),
        "NetPnL": round(gross - charges, 2),
        "GrowwExitOrderID": exit_order_id,
        "ExitOrderStatus": exit_status,
        "ExitReason": exit_reason,
    })
    return updated


def process_live(groww, selected_stocks, tf_mins, fast_len, slow_len, atr_len,
                 atr_mult, use_atr, trade_capital, leverage, slippage_bps,
                 live_trading):
    now = datetime.now(IST)
    db = load_db()

    # Outside market hours we only refresh current prices / manage already
    # existing broker positions; no new strategy entries.
    for symbol in selected_stocks:
        try:
            hist = fetch_groww_history(groww, symbol, tf_mins, days=5)
            closed = only_closed_candles(hist, tf_mins, now)
            if len(closed) < max(slow_len + 2, atr_len + 2):
                continue

            ind = add_indicators(closed, fast_len, slow_len, atr_len)
            i = len(ind) - 1
            normal_signal, reversal_signal = signal_at(ind, i)
            atr = float(ind["ATR"].iloc[i])
            signal_close = float(ind["Close"].iloc[i])

            ltp = groww_ltp(groww, symbol)

            # First reconcile existing rows and calculate live P&L.
            db = load_db()
            for mode in ("Normal", "Reversal"):
                row = find_live_row(db, symbol, mode)
                if row is None:
                    continue

                side = str(row["Type"])
                entry = float(row["EntryPrice"])
                qty = int(row["Qty"])
                gross = (ltp - entry) * qty if side == "BUY" else (entry - ltp) * qty
                charges = estimate_charges(entry, ltp, qty)
                updated = dict(row)
                updated["CurrentPrice"] = round(ltp, 2)
                updated["GrossPnL"] = round(gross, 2)
                updated["Charges"] = round(charges, 2)
                updated["NetPnL"] = round(gross - charges, 2)

                # Broker SL order is the real stop. Reconcile its status.
                slid = str(row.get("GrowwSLOrderID", "-"))
                if live_trading and slid not in ("", "-", "nan"):
                    sd = groww_order_status(groww, slid)
                    s = str(sd.get("order_status", row.get("SLOrderStatus", "")))
                    updated["SLOrderStatus"] = s
                    if s in ("EXECUTED", "COMPLETED"):
                        # Use trade details/order detail if available.
                        detail = groww_order_detail(groww, slid)
                        _, fill_price, _ = extract_fill(detail)
                        ep = fill_price if fill_price else ltp
                        gross2 = (ep - entry) * qty if side == "BUY" else (entry - ep) * qty
                        ch2 = estimate_charges(entry, ep, qty)
                        updated.update({
                            "ExitPrice": round(ep, 2),
                            "ExitTime": now.strftime("%H:%M:%S"),
                            "Status": "SL HIT (CLOSED)",
                            "GrossPnL": round(gross2, 2),
                            "Charges": ch2,
                            "NetPnL": round(gross2 - ch2, 2),
                            "ExitReason": "BROKER_SLM_EXECUTED",
                        })
                        upsert_trade_to_db(updated)
                        continue

                opposite = (side == "BUY" and reversal_signal) or (side == "SELL" and normal_signal)
                eod = should_squareoff(now)
                if market_open_now(now) and (opposite or eod):
                    reason = "OPPOSITE_CONFIRMED_SIGNAL" if opposite else "EOD_SQUARE_OFF"
                    try:
                        updated = close_live_trade(
                            groww, updated, reason, live_trading, ltp, slippage_bps
                        )
                    except Exception as exc:
                        updated["ExitReason"] = f"EXIT_ERROR: {exc}"
                    upsert_trade_to_db(updated)
                else:
                    upsert_trade_to_db(updated)

            # New entry only once per completed candle.
            if market_open_now(now) and not should_squareoff(now):
                candle_time = ind.index[i].isoformat()
                normal_key = f"{symbol}_Normal_{candle_time}"
                rev_key = f"{symbol}_Reversal_{candle_time}"

                if "processed_keys" not in st.session_state:
                    st.session_state.processed_keys = set()

                db = load_db()
                if normal_signal and find_live_row(db, symbol, "Normal") is None and normal_key not in st.session_state.processed_keys:
                    st.session_state.processed_keys.add(normal_key)
                    trade = create_live_entry(
                        groww, symbol, "Normal", "BUY", signal_close, atr,
                        atr_mult, trade_capital, leverage, use_atr, slippage_bps,
                        live_trading
                    )
                    upsert_trade_to_db(trade)

                if reversal_signal and find_live_row(db, symbol, "Reversal") is None and rev_key not in st.session_state.processed_keys:
                    st.session_state.processed_keys.add(rev_key)
                    trade = create_live_entry(
                        groww, symbol, "Reversal", "SELL", signal_close, atr,
                        atr_mult, trade_capital, leverage, use_atr, slippage_bps,
                        live_trading
                    )
                    upsert_trade_to_db(trade)

        except Exception as exc:
            st.session_state.setdefault("engine_errors", []).append(
                f"{symbol}: {type(exc).__name__}: {exc}"
            )


# =============================================================================
# BACKTEST â€” same signal/SL/exit rules, no look-ahead
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def run_60d_dual_backtest_public(stocks_list, fast_len, slow_len, atr_len,
                                  atr_mult, use_atr, trade_val, leverage,
                                  tf_mins, slippage_bps):
    # Groww credentials are required because historical data is fetched from
    # Groww, not yfinance. Token is deliberately passed only to this server
    # process and is not written to the CSV.
    token = get_secret("GROWW_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("GROWW_ACCESS_TOKEN missing in Streamlit secrets.")
    groww = get_groww_client(token)

    now = datetime.now(IST)
    end = now
    start = now - timedelta(days=90)  # enough room for a true trailing 60-day window

    norm_list, rev_list = [], []
    buying_power = float(trade_val) * float(leverage)

    for symbol in stocks_list:
        try:
            resp = groww.get_historical_candles(
                exchange=groww.EXCHANGE_NSE,
                segment=groww.SEGMENT_CASH,
                groww_symbol=f"NSE-{symbol}",
                start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval=groww_interval_constant(groww, tf_mins),
            )
            df = candles_to_df(resp)
            df = only_closed_candles(df, tf_mins, now)
            if len(df) < slow_len + 10:
                continue

            # Keep last ~60 calendar days worth of returned candles.
            df = df[df.index >= (now - timedelta(days=60))]
            df = add_indicators(df, fast_len, slow_len, atr_len)

            # A position can exist only one at a time per strategy/symbol.
            for mode, side, out_list in [
                ("Normal", "BUY", norm_list),
                ("Reversal", "SELL", rev_list),
            ]:
                open_trade = None

                for i in range(slow_len + 1, len(df) - 1):
                    # Manage existing trade first using candle i.
                    if open_trade is not None:
                        hi = float(df["High"].iloc[i])
                        lo = float(df["Low"].iloc[i])
                        close = float(df["Close"].iloc[i])
                        ts = df.index[i]

                        exit_price = None
                        reason = None

                        # Conservative intrabar rule: if SL is touched, assume
                        # SL was executed before an opposite close signal.
                        if side == "BUY" and use_atr and lo <= open_trade["SL"]:
                            exit_price = open_trade["SL"]
                            reason = "ATR_SL"
                        elif side == "SELL" and use_atr and hi >= open_trade["SL"]:
                            exit_price = open_trade["SL"]
                            reason = "ATR_SL"
                        else:
                            ns, rs = signal_at(df, i)
                            opposite = (side == "BUY" and rs) or (side == "SELL" and ns)
                            if opposite:
                                # Signal becomes known at candle close; execution
                                # is next candle OPEN, not the signal candle close.
                                if i + 1 < len(df):
                                    exit_price = apply_slippage(
                                        float(df["Open"].iloc[i + 1]),
                                        "SELL" if side == "BUY" else "BUY",
                                        slippage_bps
                                    )
                                    reason = "OPPOSITE_SIGNAL"
                                    ts = df.index[i + 1]
                        if exit_price is not None:
                            entry = open_trade["EntryPrice"]
                            qty = open_trade["Qty"]
                            gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                            charges = estimate_charges(entry, exit_price, qty)
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
                                "Charges": charges,
                                "NetPnL": round(gross - charges, 2),
                                "ExitReason": reason,
                            })
                            open_trade = None
                            # Do not open a new trade on the same bar after exit.
                            continue

                    # New signal on candle i -> enter at NEXT candle OPEN.
                    ns, rs = signal_at(df, i)
                    trigger = ns if side == "BUY" else rs
                    if trigger and open_trade is None and i + 1 < len(df):
                        entry_raw = float(df["Open"].iloc[i + 1])
                        entry = apply_slippage(entry_raw, side, slippage_bps)
                        atr = float(df["ATR"].iloc[i])
                        if use_atr and not np.isnan(atr) and atr > 0:
                            sl = entry - atr_mult * atr if side == "BUY" else entry + atr_mult * atr
                        else:
                            sl = entry * 0.95 if side == "BUY" else entry * 1.05

                        qty = max(1, int(buying_power / max(entry, 0.01)))
                        open_trade = {
                            "Date": df.index[i + 1].strftime("%Y-%m-%d"),
                            "EntryTime": df.index[i + 1].strftime("%H:%M"),
                            "EntryPrice": entry,
                            "SL": sl,
                            "Qty": qty,
                        }

                # Force EOD close for any still-open historical trade.
                if open_trade is not None:
                    entry = open_trade["EntryPrice"]
                    qty = open_trade["Qty"]
                    exit_price = float(df["Close"].iloc[-1])
                    exit_price = apply_slippage(exit_price, "SELL" if side == "BUY" else "BUY", slippage_bps)
                    gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
                    charges = estimate_charges(entry, exit_price, qty)
                    out_list.append({
                        "Date": open_trade["Date"],
                        "EntryTime": open_trade["EntryTime"],
                        "ExitTime": df.index[-1].strftime("%H:%M"),
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": side,
                        "Qty": qty,
                        "EntryPrice": round(entry, 2),
                        "ExitPrice": round(exit_price, 2),
                        "SL": round(open_trade["SL"], 2),
                        "GrossPnL": round(gross, 2),
                        "Charges": charges,
                        "NetPnL": round(gross - charges, 2),
                        "ExitReason": "BACKTEST_END",
                    })
        except Exception:
            continue

    norm = pd.DataFrame(norm_list)
    rev = pd.DataFrame(rev_list)
    if not norm.empty:
        norm.insert(0, "Sr", range(1, len(norm) + 1))
    if not rev.empty:
        rev.insert(0, "Sr", range(1, len(rev) + 1))
    return norm, rev


# =============================================================================
# SIDEBAR â€” same controls + Groww live control
# =============================================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = DEFAULT_STOCKS.copy()

with st.sidebar:
    st.header("ðŸ” Dynamic Share Selection")
    new_stock = st.text_input("Add Custom NSE Ticker (e.g. ZOMATO):", "").strip().upper()
    if st.button("âž• Add Share to Watchlist"):
        if new_stock:
            formatted = new_stock if new_stock.endswith(".NS") else f"{new_stock}.NS"
            if formatted not in st.session_state.watchlist:
                st.session_state.watchlist.append(formatted)
                st.success(f"{formatted} added!")
                st.rerun()

    SELECTED_STOCKS = st.multiselect(
        "Active Watchlist (Max 10):",
        options=st.session_state.watchlist,
        default=st.session_state.watchlist[:5],
        max_selections=10,
    )

    st.markdown("---")
    st.header("âš™ï¸ Strategy Parameters")
    FAST_MA_LEN = st.number_input("Fast EMA Length", value=20, step=5)
    SLOW_MA_LEN = st.number_input("Slow EMA Length", value=50, step=5)
    USE_ATR_STOP = st.checkbox("Use ATR Stop Loss", value=True)
    ATR_LEN = st.number_input("ATR Length", value=14, step=1)
    ATR_MULT = st.number_input("ATR Multiplier", value=3.0, step=0.5)

    st.subheader("ðŸ’° Execution & Margin Settings")
    TRADE_VALUE = st.number_input("Trade Capital per Stock (Rs)", value=3000, step=500)
    LEVERAGE = st.number_input("Intraday Margin Leverage (e.g. 5x)", value=5, min_value=1, max_value=20, step=1)
    TIMEFRAME_MINS = st.selectbox("Candle Timeframe (Minutes)", [5, 15, 30, 60], index=1)
    SLIPPAGE_BPS = st.number_input("Backtest Slippage (bps)", value=5.0, min_value=0.0, step=1.0)

    st.markdown("---")
    st.subheader("ðŸ” Groww Real Trading")
    live_trading_secret = str(get_secret("LIVE_TRADING", "false")).lower() == "true"
    LIVE_TRADING = st.checkbox(
        "âš ï¸ Enable REAL Groww Orders",
        value=False,
        help="Real orders are sent only when LIVE_TRADING=true is also present in Streamlit secrets."
    )
    if LIVE_TRADING and not live_trading_secret:
        st.error("REAL trading locked: set LIVE_TRADING=true in Streamlit secrets.")
        LIVE_TRADING = False

    AUTO_REFRESH = st.checkbox("ðŸ”„ Auto-Refresh Live P&L (15 sec)", value=True)

    if st.button("ðŸ—‘ï¸ Reset Entire History DB"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.session_state.processed_keys = set()
        st.success("History database reset ho gaya!")
        st.rerun()

if not SELECTED_STOCKS:
    st.warning("âš ï¸ Kam se kam 1 share select karein.")
    st.stop()

if "processed_keys" not in st.session_state:
    st.session_state.processed_keys = set()
if "engine_errors" not in st.session_state:
    st.session_state.engine_errors = []


# =============================================================================
# CONNECT + PROCESS
# =============================================================================
token = get_secret("GROWW_ACCESS_TOKEN", "")
groww = get_groww_client(token) if token and GrowwAPI is not None else None

if groww is None:
    st.error("Groww API connect nahi hua. Streamlit secrets mein GROWW_ACCESS_TOKEN set karein aur `pip install growwapi` karein.")
else:
    try:
        process_live(
            groww, SELECTED_STOCKS, TIMEFRAME_MINS,
            int(FAST_MA_LEN), int(SLOW_MA_LEN), int(ATR_LEN), float(ATR_MULT),
            bool(USE_ATR_STOP), float(TRADE_VALUE), float(LEVERAGE),
            float(SLIPPAGE_BPS), bool(LIVE_TRADING)
        )
    except Exception as exc:
        st.error(f"Live engine error: {type(exc).__name__}: {exc}")


# =============================================================================
# DASHBOARD RENDERERS â€” same tabs/cards
# =============================================================================
def render_live_strategy_tab(strategy_mode, title):
    st.markdown(f"### {title}")
    db_df = load_db()
    mode_df = db_df[db_df["StrategyMode"] == strategy_mode] if not db_df.empty else pd.DataFrame()

    total_trades = len(mode_df)
    tot_gross = mode_df["GrossPnL"].astype(float).sum() if not mode_df.empty else 0.0
    tot_charges = mode_df["Charges"].astype(float).sum() if not mode_df.empty else 0.0
    tot_net = round(tot_gross - tot_charges, 2)

    net_class = "metric-val-green" if tot_net >= 0 else "metric-val-red"
    gross_class = "metric-val-green" if tot_gross >= 0 else "metric-val-red"

    st.markdown(f"""
    <div class="top-pnl-card">
        <div style="display:flex;justify-content:space-around;text-align:center;">
            <div><span style="font-size:12px;color:#8b949e;">TOTAL TRADES</span><br>
            <span style="font-size:18px;font-weight:bold;">{total_trades}</span></div>
            <div><span style="font-size:12px;color:#8b949e;">GROSS P&L</span><br>
            <span class="{gross_class}">{RUPEE}{tot_gross:.2f}</span></div>
            <div><span style="font-size:12px;color:#8b949e;">TOTAL CHARGES</span><br>
            <span style="font-size:18px;font-weight:bold;color:#e3b341;">{RUPEE}{tot_charges:.2f}</span></div>
            <div><span style="font-size:12px;color:#8b949e;">NET REALIZED P&L</span><br>
            <span class="{net_class}">{RUPEE}{tot_net:.2f}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if mode_df.empty:
        st.info("Koi active ya closed trade record nahi mila.")
        return

    active_df = mode_df[mode_df["Status"].isin(["LIVE", "ENTRY_PENDING", "SL_PENDING"])].copy()
    closed_df = mode_df[~mode_df["Status"].isin(["LIVE", "ENTRY_PENDING", "SL_PENDING"])].copy()

    col_order = [
        "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type", "Qty",
        "EntryPrice", "CurrentPrice", "ExitPrice", "SL", "Status",
        "GrossPnL", "Charges", "NetPnL"
    ]

    st.markdown("#### ðŸŸ¢ Active (LIVE) Positions")
    if not active_df.empty:
        active_df["Sr"] = range(1, len(active_df) + 1)
        st.dataframe(active_df[col_order], use_container_width=True, hide_index=True)
    else:
        st.caption("Abhi koi open position nahi hai.")

    st.markdown("#### ðŸ—„ï¸ Closed Trades History")
    if not closed_df.empty:
        closed_df["Sr"] = range(1, len(closed_df) + 1)
        st.dataframe(closed_df[col_order], use_container_width=True, hide_index=True)
    else:
        st.caption("Abhi tak koi trade close nahi hua hai.")


# =============================================================================
# APP TABS â€” unchanged dashboard structure
# =============================================================================
tab1, tab2, tab3 = st.tabs([
    "ðŸŸ¢ Tab 1: Live Normal Strategy",
    "ðŸ”´ Tab 2: Live Reversal Strategy",
    "ðŸ“Š Tab 3: Backtest & History Database"
])

with tab1:
    render_live_strategy_tab("Normal", "ðŸŸ¢ Live Normal Strategy Terminal")

with tab2:
    render_live_strategy_tab("Reversal", "ðŸ”´ Live Reversal Strategy Terminal")

with tab3:
    st.markdown("### ðŸ“Š Dual Backtest Engine & Database Logs")
    col_btn, _ = st.columns([1, 4])
    with col_btn:
        run_btn = st.button("â–¶ï¸ Run 60-Day Backtest", type="primary")

    if run_btn:
        with st.spinner("Groww historical data par 60-day backtest calculate ho raha hai..."):
            try:
                norm_bt, rev_bt = run_60d_dual_backtest_public(
                    tuple(SELECTED_STOCKS), int(FAST_MA_LEN), int(SLOW_MA_LEN),
                    int(ATR_LEN), float(ATR_MULT), bool(USE_ATR_STOP),
                    float(TRADE_VALUE), float(LEVERAGE), int(TIMEFRAME_MINS),
                    float(SLIPPAGE_BPS)
                )
                st.session_state.norm_bt = norm_bt
                st.session_state.rev_bt = rev_bt
            except Exception as exc:
                st.error(f"Backtest error: {type(exc).__name__}: {exc}")

    norm_bt = st.session_state.get("norm_bt")
    rev_bt = st.session_state.get("rev_bt")

    if norm_bt is not None and rev_bt is not None:
        c1, c2 = st.columns(2)

        def render_bt_summary(df, name):
            if df.empty:
                st.warning(f"No trades generated for {name}")
                return

            tot = len(df)
            wins = len(df[df["NetPnL"] > 0])
            wr = round((wins / tot) * 100, 1)
            gross_pnl = round(df["GrossPnL"].sum(), 2)
            charges = round(df["Charges"].sum(), 2)
            net_pnl = round(df["NetPnL"].sum(), 2)
            net_class = "metric-val-green" if net_pnl >= 0 else "metric-val-red"

            bt_col_order = [
                "Sr", "Date", "EntryTime", "ExitTime", "Symbol", "Type",
                "Qty", "EntryPrice", "ExitPrice", "SL", "GrossPnL",
                "Charges", "NetPnL", "ExitReason"
            ]

            st.markdown(f"#### {name}")
            st.markdown(f"""
            <div class="top-pnl-card">
                <b>Total Trades:</b> {tot} | <b>Win Rate:</b> {wr}%<br>
                <b>Gross P&L:</b> {RUPEE}{gross_pnl} |
                <b>Total Charges:</b> <span style="color:#e3b341;">{RUPEE}{charges}</span><br>
                <b>Net P&L:</b> <span class="{net_class}">{RUPEE}{net_pnl}</span>
            </div>
            """, unsafe_allow_html=True)
            st.dataframe(df[bt_col_order], use_container_width=True, hide_index=True)

        with c1:
            render_bt_summary(norm_bt, "Normal Trend Strategy")
        with c2:
            render_bt_summary(rev_bt, "Reversal Contra Strategy")

    st.markdown("---")
    st.markdown("### ðŸ—„ï¸ All Live & Closed Trades Master Database")
    db_df = load_db()
    if not db_df.empty:
        st.dataframe(db_df, use_container_width=True, hide_index=True)
    else:
        st.info("Abhi tak koi trade database mein save nahi hua hai.")

if st.session_state.engine_errors:
    with st.expander("Engine diagnostics"):
        for e in st.session_state.engine_errors[-20:]:
            st.write(e)

if AUTO_REFRESH:
    time.sleep(15)
    st.rerun()
