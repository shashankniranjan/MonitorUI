import streamlit as st
import time
import requests
import json
import hmac
import hashlib
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
            "size": "1"
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = getSignature(json_body, api_secret)

        resp = requests.post(
            f"{url}/derivatives/futures/positions/",
            data=json_body,  # or json=body if the API expects JSON
            headers=get_header(api_key, signature),
            timeout=10
        )
        resp.raise_for_status()

        positions = resp.json()
        return positions  # Could be a list or dict depending on the API
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

    BUY_OR_SELL: 'buy' or 'sell' side of the position
    quantity: how many units to close
    paper_trade: if True, do not actually hit the API (just a mock)
    position_id: ID of the position to close
    """
    if paper_trade:
        # If you're doing a 'paper trade', just skip the real API call
        st.info(f"Paper trade mode: Position {position_id} would have been closed.")
        return {"status": "paper_trade", "position_id": position_id}

    try:
        timestamp = int(round(time.time() * 1000))
        body = {
            "timestamp": timestamp,
            "id": position_id
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = getSignature(json_body, api_secret)

        resp = requests.post(
            f"{url}/derivatives/futures/positions/exit",
            data=json_body,
            headers=get_header(api_key, signature),
            timeout=10
        )
        # Raise if 4xx/5xx
        resp.raise_for_status()
        response_json = resp.json()

        # The API might put success info in 'message' or 'id' or something else
        if response_json.get('message'):
            return {
                "status": "success",
                "details": response_json
            }
        else:
            return {
                "status": "fail",
                "details": response_json
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

#############################################
# 3) Function to close *all* positions
#    UPDATED for new payload structure
#############################################
def close_all_positions(
        url: str,
        api_key: str,
        api_secret: str,
        paper_trade: bool = False
) -> List[dict]:
    """
    1) Lists all open positions
    2) For each position, determines side ('buy' or 'sell') from 'active_pos'
    3) Calls close_position_by_position_id for each position
    4) Returns a list of results
    """
    results = []
    all_positions = list_positions(url, api_key, api_secret)
    if not all_positions:
        return []

    # The new payload for each position might look like:
    # {
    #   "id": "267b6998-7249-11ef-a59c-73fd5f213418",
    #   "pair": "B-BTC_USDT",
    #   "active_pos": 0.002,  # positive -> LONG, negative -> SHORT, zero -> no position
    #   ...
    # }

    for pos in all_positions:
        position_id = pos.get("id")
        active_pos = pos.get("active_pos", 0.0)  # Could be float or int

        # If active_pos > 0 => LONG => need to SELL to close
        # If active_pos < 0 => SHORT => need to BUY to close
        # If zero => skip
        if not position_id:
            # Skip if missing an ID
            continue

        if active_pos > 0:
            side = "sell"
            quantity = active_pos  # float
        elif active_pos < 0:
            side = "buy"
            quantity = abs(active_pos)
        else:
            # active_pos == 0 => no position to close
            continue

        # Now call the close function
        result = close_position_by_position_id(
            BUY_OR_SELL=side,       # 'sell' or 'buy'
            quantity=quantity,      # absolute value
            paper_trade=paper_trade,
            api_key=api_key,
            api_secret=api_secret,
            url=url,
            position_id=position_id
        )
        results.append({
            "position_id": position_id,
            "close_result": result
        })
        print(f"Closed position {position_id} -> {result}")

    return results
#############################################
# 4) Streamlit UI
#############################################
def main():
    st.title("CoinDCX Futures Dashboard")

    api_url = st.text_input("API Base URL", "https://api.coindcx.com/exchange/v1")
    api_key = st.secrets["connections"]["api_key"]
    api_secret = st.secrets["connections"]["api_secret"]

    # Fetch positions
    if st.button("Fetch Open Positions"):
        if not api_url or not api_key or not api_secret:
            st.error("Please fill in all fields!")
        else:
            positions = list_positions(api_url, api_key, api_secret)
            if positions:
                st.write("Open Positions:")
                st.json(positions)  # or st.write() or st.table(...) if it's tabular
            else:
                st.info("No open positions found or error occurred.")

    # Close all positions
    if st.button("Close All Positions"):
        if not api_url or not api_key or not api_secret:
            st.error("Please fill in all fields!")
        else:
            st.write("Attempting to close all positions...")
            results = close_all_positions(api_url, api_key, api_secret, paper_trade=False)

            if results:
                st.write("Close results:")
                st.json(results)
            else:
                st.info("No positions were closed (maybe none were open).")

if __name__ == "__main__":
    main()