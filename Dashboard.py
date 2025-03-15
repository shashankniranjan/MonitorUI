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
            data=json_body,  # or use json=body if required
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
        position_id: str
):
    """
    Closes a specific position using the endpoint:
    f"{url}/derivatives/futures/positions/exit"
    """
    if paper_trade:
        st.info(f"Paper trade mode: Position {position_id} would have been closed.")
        return {"status": "paper_trade", "position_id": position_id}

    try:
        timestamp = int(round(time.time() * 1000))
        body = {
            "timestamp": timestamp,
            "id": position_id
            # Add other fields if needed by the API (e.g., symbol, side, quantity)
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = getSignature(json_body, api_secret)

        resp = requests.post(
            f"{url}/derivatives/futures/positions/exit",
            data=json_body,
            headers=get_header(api_key, signature),
            timeout=10
        )
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
    1) Lists all positions
    2) Determines side ('buy'/'sell') from 'active_pos'
    3) Calls close_position_by_position_id for each non-zero position
    4) Returns a list of results
    """
    results = []
    all_positions = list_positions(url, api_key, api_secret)
    if not all_positions:
        return []

    for pos in all_positions:
        position_id = pos.get("id")
        active_pos = pos.get("active_pos", 0.0)

        if not position_id:
            continue
        if active_pos > 0:
            side = "sell"             # Close a long position
            quantity = active_pos
        elif active_pos < 0:
            side = "buy"              # Close a short position
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
            position_id=position_id
        )
        results.append({"position_id": position_id, "close_result": result})
    return results

#############################################
# 4) Helper to convert timestamp to IST
#############################################
def to_ist(epoch_ms: int) -> str:
    """
    Convert epoch ms to a readable IST time string.
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

    # Close All Positions button with confirmation and check for open positions
    if st.button("Close All Positions"):
        if not st.session_state["positions"]:
            st.warning("No open positions to close!")
        else:
            confirm_close = st.checkbox("Are you sure you want to close all positions?")
            if confirm_close:
                st.write("Closing all positions...")
                results = close_all_positions(api_url, api_key, api_secret, paper_trade=False)
                if results:
                    st.write("Close results:")
                    st.json(results)
                    # Refresh positions after closing
                    st.session_state["positions"] = list_positions(api_url, api_key, api_secret) or []
                else:
                    st.info("No positions were closed (maybe none were open).")
            else:
                st.warning("Please check the box to confirm closing all positions.")

if __name__ == "__main__":
    main()