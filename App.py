from collections import deque
from datetime import datetime, timedelta
import math
import time
from growwapi import GrowwAPI

# ==============================================================================
# CONFIGURATION
# ==============================================================================
api_key = "YOUR_API_KEY_HERE"
secret = "YOUR_SECRET_HERE"

CAPITAL_PER_TRADE = 50000.0  # ₹50,000 Budget per stock trade
TIMEFRAME = 5  # 5-Minute Candles (As per Code 1 Pullback Strategy)

# F&O / High Liquidity Stock Symbols for Groww API
STOCKS = [
    "NSE_RELIANCE",
    "NSE_HDFCBANK",
    "NSE_ICICIBANK",
    "NSE_INFY",
    "NSE_TCS",
    "NSE_SBIN",
    "NSE_BHARTIARTL",
    "NSE_TATAMOTORS",
    "NSE_AXISBANK",
    "NSE_MARUTI",
]

stock_data = {}

# Initialize Groww API
try:
    access_token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
    groww = GrowwAPI(access_token)
    PRODUCT_TYPE = groww.PRODUCT_MIS  # Intraday Order Type
    print("✅ Successfully connected to Groww API!")
except Exception as e:
    print(f"❌ Groww API Connection Failed: {e}")
    exit(1)


# ==============================================================================
# DATA PARSING HELPERS
# ==============================================================================
def get_historical_data(symbol, days=5):
    """Fetch 5-minute historical candle data for 3-Candle Pullback Scanner."""
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    try:
        data = groww.get_historical_candle_data(
            trading_symbol=symbol.replace("NSE_", ""),
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=TIMEFRAME,
        )
        return data
    except Exception as e:
        print(f"❌ Error fetching data for {symbol}: {e}")
        return None


def extract_candles(response):
    if isinstance(response, dict):
        if "candles" in response:
            return response["candles"]
        elif "data" in response:
            return (
                response["data"].get("candles", [])
                if isinstance(response["data"], dict)
                else response["data"]
            )
    elif isinstance(response, list):
        return response
    return []


def extract_candle_ohlcv(candle):
    """Parses OHLCV candle structure."""
    if isinstance(candle, list) and len(candle) >= 6:
        return (
            candle[0],
            float(candle[1]),
            float(candle[2]),
            float(candle[3]),
            float(candle[4]),
            float(candle[5]),
        )
    elif isinstance(candle, dict):
        return (
            candle.get("time"),
            float(candle.get("open", 0)),
            float(candle.get("high", 0)),
            float(candle.get("low", 0)),
            float(candle.get("close", 0)),
            float(candle.get("volume", 0)),
        )
    return None, None, None, None, None, None


# ==============================================================================
# STRATEGY ENGINE (3-CANDLE PULLBACK FROM CODE 1)
# ==============================================================================
def analyze_3candle_pullback(processed_candles):
    """Exact logic from Code 1:

    3 Consecutive Green/Red Candles + Low Volume Pullback Candle.
    """
    if len(processed_candles) < 4:
        return None

    c1, c2, c3, curr = (
        processed_candles[-4],
        processed_candles[-3],
        processed_candles[-2],
        processed_candles[-1],
    )

    c1_green = c1["close"] > c1["open"]
    c2_green = c2["close"] > c2["open"]
    c3_green = c3["close"] > c3["open"]

    c1_red = c1["close"] < c1["open"]
    c2_red = c2["close"] < c2["open"]
    c3_red = c3["close"] < c3["open"]

    initial_3_avg_vol = (c1["volume"] + c2["volume"] + c3["volume"]) / 3.0

    # BUY SETUP
    if c1_green and c2_green and c3_green:
        if (
            curr["close"] < curr["open"]
            and curr["volume"] < initial_3_avg_vol
        ):
            entry = curr["high"]
            sl = round(curr["low"] * 0.997, 2)  # 0.3% Buffer
            risk = entry - sl
            target = round(entry + (risk * 2), 2)  # 1:2 R:R Ratio
            qty = max(1, int(CAPITAL_PER_TRADE // entry))

            return {
                "signal": "BUY",
                "entry": round(entry, 2),
                "sl": sl,
                "target": target,
                "qty": qty,
            }

    # SELL SETUP
    if c1_red and c2_red and c3_red:
        if (
            curr["close"] > curr["open"]
            and curr["volume"] < initial_3_avg_vol
        ):
            entry = curr["low"]
            sl = round(curr["high"] * 1.003, 2)  # 0.3% Buffer
            risk = sl - entry
            target = round(entry - (risk * 2), 2)  # 1:2 R:R Ratio
            qty = max(1, int(CAPITAL_PER_TRADE // entry))

            return {
                "signal": "SELL",
                "entry": round(entry, 2),
                "sl": sl,
                "target": target,
                "qty": qty,
            }

    return None


# ==============================================================================
# ORDER EXECUTION ENGINE
# ==============================================================================
def execute_trade(stock_symbol, signal_data):
    """Executes Buy/Sell orders on Groww API."""
    stock_info = stock_data[stock_symbol]
    trading_symbol = stock_symbol.replace("NSE_", "")
    sig_type = signal_data["signal"]
    qty = signal_data["qty"]

    trans_type = (
        groww.TRANSACTION_TYPE_BUY
        if sig_type == "BUY"
        else groww.TRANSACTION_TYPE_SELL
    )

    try:
        print(f"\n🚀 EXECUTION TRIGGERED FOR [{trading_symbol}]")
        print(
            f"   • Signal: {sig_type} | Qty: {qty} shares (Capital Budget: ₹50,000)"
        )
        print(f"   • Entry Price: ₹{signal_data['entry']}")
        print(f"   • Stop Loss (SL): ₹{signal_data['sl']}")
        print(f"   • Target (1:2 R:R): ₹{signal_data['target']}")

        order = groww.place_order(
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            order_type=groww.ORDER_TYPE_MARKET,
            product=PRODUCT_TYPE,
            quantity=qty,
            segment=groww.SEGMENT_CASH,
            trading_symbol=trading_symbol,
            transaction_type=trans_type,
            price=0.0,
        )

        stock_info["position"] = 1 if sig_type == "BUY" else -1
        stock_info["entry_price"] = signal_data["entry"]
        stock_info["sl_price"] = signal_data["sl"]
        stock_info["target_price"] = signal_data["target"]
        stock_info["qty"] = qty

        print(
            f"   ✅ Order Executed Successfully! Order ID: {order.get('groww_order_id', 'N/A')}\n"
        )
        return True
    except Exception as e:
        print(f"   ❌ Order Placement Error: {e}\n")
        return False


def close_position(stock_symbol, current_price, reason="EXIT"):
    """Exits Active Positions on Target or SL Hit."""
    stock_info = stock_data[stock_symbol]
    trading_symbol = stock_symbol.replace("NSE_", "")
    qty = stock_info["qty"]
    pos = stock_info["position"]

    trans_type = (
        groww.TRANSACTION_TYPE_SELL
        if pos == 1
        else groww.TRANSACTION_TYPE_BUY
    )

    try:
        print(f"\n⚠️ [{trading_symbol}] {reason} TRIGGERED @ ₹{current_price:.2f}")

        order = groww.place_order(
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            order_type=groww.ORDER_TYPE_MARKET,
            product=PRODUCT_TYPE,
            quantity=qty,
            segment=groww.SEGMENT_CASH,
            trading_symbol=trading_symbol,
            transaction_type=trans_type,
            price=0.0,
        )

        if pos == 1:
            pnl = (current_price - stock_info["entry_price"]) * qty
        else:
            pnl = (stock_info["entry_price"] - current_price) * qty

        print(f"   📊 Trade Closed. Realized P&L: ₹{pnl:+.2f}")

        # Reset stock position state
        stock_info["position"] = 0
        stock_info["entry_price"] = 0.0
        stock_info["sl_price"] = 0.0
        stock_info["target_price"] = 0.0
        stock_info["qty"] = 0
        return True
    except Exception as e:
        print(f"   ❌ Position Close Error: {e}\n")
        return False


# ==============================================================================
# INITIALIZATION & MONITORING LOOP
# ==============================================================================
print("\n" + "=" * 70)
print("📊 INITIALIZING 3-CANDLE PULLBACK TRADING ENGINE (GROWW LIVE)")
print("=" * 70)

for stock in STOCKS:
    stock_data[stock] = {
        "position": 0,  # 1 = Long, -1 = Short, 0 = Flat
        "entry_price": 0.0,
        "sl_price": 0.0,
        "target_price": 0.0,
        "qty": 0,
    }

print(f"✅ Scanning initial setups for {len(STOCKS)} stocks...")

while True:
    try:
        for stock_symbol in STOCKS:
            trading_symbol = stock_symbol.replace("NSE_", "")
            stock_info = stock_data[stock_symbol]

            # 1. Fetch candles
            raw_data = get_historical_data(stock_symbol, days=2)
            candles = extract_candles(raw_data)

            processed_candles = []
            for c in candles:
                ts, o, h, l, cl, v = extract_candle_ohlcv(c)
                if cl is not None:
                    processed_candles.append(
                        {
                            "time": ts,
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": cl,
                            "volume": v,
                        }
                    )

            if len(processed_candles) < 4:
                continue

            current_price = processed_candles[-1]["close"]

            # 2. Check for SL / Target Hits if Position is ACTIVE
            if stock_info["position"] == 1:  # Long Position
                if current_price >= stock_info["target_price"]:
                    close_position(
                        stock_symbol, current_price, reason="TARGET HIT 🎯"
                    )
                elif current_price <= stock_info["sl_price"]:
                    close_position(
                        stock_symbol, current_price, reason="STOP LOSS HIT 🛑"
                    )

            elif stock_info["position"] == -1:  # Short Position
                if current_price <= stock_info["target_price"]:
                    close_position(
                        stock_symbol, current_price, reason="TARGET HIT 🎯"
                    )
                elif current_price >= stock_info["sl_price"]:
                    close_position(
                        stock_symbol, current_price, reason="STOP LOSS HIT 🛑"
                    )

            # 3. Check for NEW Setup Signal if FLAT
            elif stock_info["position"] == 0:
                signal_data = analyze_3candle_pullback(processed_candles)
                if signal_data:
                    execute_trade(stock_symbol, signal_data)

            # 4. Status Print
            pos_str = (
                "BUY ACTIVE"
                if stock_info["position"] == 1
                else (
                    "SELL ACTIVE" if stock_info["position"] == -1 else "SCANNING"
                )
            )
            print(
                f"\r[{trading_symbol}] Price: ₹{current_price:.2f} | Status: {pos_str}",
                end="",
                flush=True,
            )

        time.sleep(5)  # Scan every 5 seconds

    except KeyboardInterrupt:
        print("\n🛑 Stopped by User.")
        break
    except Exception as e:
        print(f"\n❌ Error in live loop: {e}")
        time.sleep(5)
