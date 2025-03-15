import streamlit as st
import time
import requests
import json
import hmac
import hashlib
import datetime
import pytz
from typing import Optional, Dict, Any, List

#############################################
# Utilities for signing and headers
#############################################
def getSignature(json_body: str, secret: str) -> str:
    return hmac.new(
        bytes(secret, encoding='utf-8'),
        json_body.encode(),
        hashlib.sha256
    ).hexdigest()

def get_header(api_key: str, signature: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": api_key,
        "X-AUTH-SIGNATURE": signature
    }

#############################################
# 1) Function to list positions
#############################################
def list_positions(url: str, api_key: str, api_secret: str):
    """
    Fetch open positions from endpoint: f"{url}/derivatives/futures/positions"
    """
    try:
        timestamp = int(round(time.time() * 1000))
        body = {
            "timestamp": timestamp,
            "page": "1",
            "size": "10"
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = getSignature(json_body, api_secret)

        resp = requests.post(
            f"{url}/derivatives/futures/positions/",
            data=json_body,  # or use json=body if required by the API
            headers=get_header(api_key, signature),
            timeout=10
        )
        resp.raise_for_status()
        positions = resp.json()
        return positions
    except Exception as e:
        st.error(f"Error fetching positions: {e}")
        return None

#############################################
# 2) Function to close position by ID
#############################################
def close_position_by_position_id(
        BUY_OR_SELL: str,
        quantity: float,
        paper_trade: bool,
        api_key: str,
        api_secret: str,
        url: str,
        position_id: str,
        symbol: str
):
    """
    Closes a specific position using the endpoint:
    f"{url}/derivatives/futures/positions/exit"

    BUY_OR_SELL: 'buy' or 'sell' side of the position (to close LONG, use 'sell'; to close SHORT, use 'buy')
    quantity: number of units to close
    paper_trade: if True, no real API call is made
    position_id: ID of the position to close
    symbol: symbol to close (e.g. 'BTCUSDT')
    """
    if paper_trade:
        st.info(f"Paper trade mode: Position {position_id} would have been closed.")
        return {"status": "paper_trade", "position_id": position_id}

    try:
        timestamp = int(round(time.time() * 1000))
        # Build payload with additional required fields
        body = {
            "timestamp": timestamp,
            "id": position_id,
            "symbol": symbol,
            "side": BUY_OR_SELL,
            "type": "MARKET",
            "quantity": str(quantity),
            "reduceOnly": True
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = getSignature(json_body, api_secret)

        resp = requests.post(
            f"{url}/derivatives/futures/positions/exit",
            data=json_body,
            headers=get_header(api_key, signature),
            timeout=10
        )
        st.write("Close response status:", resp.status_code)
        st.write("Close response text:", resp.text)
        resp.raise_for_status()
        response_json = resp.json()
        if response_json.get('message'):
            return {"status": "success", "details": response_json}
        else:
            return {"status": "fail", "details": response_json}
    except Exception as e:
        return {"status": "error", "error": str(e)}

#############################################
# 3) Function to close *all* positions
#############################################
def close_all_positions(
        url: str,
        api_key: str,
        api_secret: str,
        paper_trade: bool = False
) -> List[dict]:
    """
    1) Lists all positions.
    2) For each position with non-zero active_pos, determines side from active_pos and extracts symbol.
    3) Calls close_position_by_position_id for each.
    4) Returns a list of results.
    """
    results = []
    all_positions = list_positions(url, api_key, api_secret)
    if not all_positions:
        return []

    for pos in all_positions:
        position_id = pos.get("id")
        active_pos = pos.get("active_pos", 0.0)
        pair = pos.get("pair", "")  # e.g., "B-BTC_USDT"
        if not position_id:
            continue

        # Extract symbol: remove leading "B-" if present.
        symbol = pair[2:] if pair.startswith("B-") else pair

        # Determine side and quantity based on active_pos
        if active_pos > 0:
            side = "sell"  # Closing a LONG requires selling.
            quantity = active_pos
        elif active_pos < 0:
            side = "buy"   # Closing a SHORT requires buying.
            quantity = abs(active_pos)
        else:
            continue  # Nothing to close if active_pos is zero

        result = close_position_by_position_id(
            BUY_OR_SELL=side,
            quantity=quantity,
            paper_trade=paper_trade,
            api_key=api_key,
            api_secret=api_secret,
            url=url,
            position_id=position_id,
            symbol=symbol
        )
        results.append({"position_id": position_id, "close_result": result})
    return results

#############################################
# 4) Helper to convert timestamp to IST
#############################################
def to_ist(epoch_ms: int) -> str:
    """
    Convert epoch milliseconds to a readable IST time string.
    """
    if not epoch_ms:
        return ""
    ist = pytz.timezone("Asia/Kolkata")
    dt_utc = datetime.datetime.utcfromtimestamp(epoch_ms / 1000.0)
    dt_ist = dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone(ist)
    return dt_ist.strftime("%Y-%m-%d %H:%M:%S")

#############################################
# 5) Format positions into a table-friendly structure
#############################################
def format_positions(positions: List[dict]) -> List[dict]:
    table_data = []
    for pos in positions:
        pid = pos.get("id")
        pair = pos.get("pair", "")
        active_pos = pos.get("active_pos", 0.0)
        updated_at = pos.get("updated_at", 0)
        avg_price = pos.get("avg_price", None)  # Extract filled price

        # Determine side based on active_pos
        if active_pos > 0:
            side = "LONG"
        elif active_pos < 0:
            side = "SHORT"
        else:
            side = "NONE"

        updated_at_str = to_ist(updated_at)

        table_data.append({
            "Position ID": pid,
            "Pair": pair,
            "Active Pos": active_pos,
            "Side": side,
            "Filled Price": avg_price,
            "Updated (IST)": updated_at_str
        })
    return table_data

#############################################
# 6) Streamlit UI
#############################################
def main():
    st.title("CoinDCX Futures Dashboard")

    # Hard-coded API Base URL (removed from UI)
    api_url = "https://api.coindcx.com/exchange/v1"

    # Load API credentials from secrets
    api_key = st.secrets["connections"]["api_key"]
    api_secret = st.secrets["connections"]["api_secret"]

    # Fetch positions on first load if not in session state
    if "positions" not in st.session_state:
        st.session_state["positions"] = list_positions(api_url, api_key, api_secret) or []

    # Display open positions as a table
    if st.session_state["positions"]:
        formatted = format_positions(st.session_state["positions"])
        st.write("Open Positions:")
        st.table(formatted)
    else:
        st.info("No open positions found.")

    # Refresh positions button
    if st.button("Refresh"):
        new_positions = list_positions(api_url, api_key, api_secret)
        if new_positions:
            st.session_state["positions"] = new_positions
            st.success("Positions refreshed!")
        else:
            st.info("No open positions found.")
        if st.session_state["positions"]:
            formatted = format_positions(st.session_state["positions"])
            st.table(formatted)

    st.write("---")

    # Render confirmation checkbox outside the button so its state is preserved
    confirm_close = st.checkbox("Are you sure you want to close all positions?", key="confirm_close")

    # Close All Positions button
    if st.button("Close All Positions"):
        if not st.session_state["positions"]:
            st.warning("No open positions to close!")
        elif not confirm_close:
            st.warning("Please check the box to confirm closing all positions.")
        else:
            st.write("Closing all positions...")
            results = close_all_positions(api_url, api_key, api_secret, paper_trade=False)
            st.write("Close results:")
            st.json(results)
            # Refresh positions after closing
            st.session_state["positions"] = list_positions(api_url, api_key, api_secret) or []
            if st.session_state["positions"]:
                formatted = format_positions(st.session_state["positions"])
                st.table(formatted)
            else:
                st.info("No open positions remain.")

if __name__ == "__main__":
    main()