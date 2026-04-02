import asyncio
import json

import requests
import websockets
from websockets.exceptions import ConnectionClosed

from handler import handle_type_13

# URI = "wss://chat.kirka.io"
URI = "wss://local.amcalledglitchy.dev:8765"
TOKEN_URL = "https://login.xsolla.com/api/oauth2/token"

# load creds properly
with open("creds.json", "r") as f:
    creds = json.load(f)

token = creds.get("token", "")
refresh_token = creds["refresh_token"]


def refresh_tokens():
    global token, refresh_token

    data = {
        "grant_type": "refresh_token",
        "client_id": "303",
        "redirect_uri": "https://kirka.io",
        "refresh_token": refresh_token,
    }

    headers = {
        "Origin": "https://kirka.io",
        "User-Agent": "Mozilla/5.0",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "websocket",
        "Sec-Fetch-Site": "same-site",
    }

    r = requests.post(TOKEN_URL, data=data, headers=headers)
    r.raise_for_status()
    res = r.json()

    token = res["access_token"]
    refresh_token = res["refresh_token"]

    # persist updated tokens
    with open("creds.json", "w") as f:
        json.dump({"token": token, "refresh_token": refresh_token}, f)

    print("Token refreshed")


async def listen():
    global token

    while True:  # reconnect loop
        try:
            if not token:
                print("no token, refreshing")
                refresh_tokens()
            async with websockets.connect(
                URI,
                subprotocols=[f"{token}----------0"],  # pyright: ignore # stfu
            ) as ws:
                print("Connected")

                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)

                    if isinstance(data, dict) and data.get("type") == 13:
                        await handle_type_13(data, ws)

        except ConnectionClosed as e:
            print("Connection closed:", e)

            # try refreshing token before reconnect
            try:
                refresh_tokens()
            except Exception as err:
                print("Refresh failed:", err)
                await asyncio.sleep(5)

        except Exception as e:
            print("Error:", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(listen())
