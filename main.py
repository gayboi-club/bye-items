import asyncio
import json

from kirkaio import KirkaChatBot
from websockets import ClientConnection

with open("creds.json") as fp:
    creds = json.load(fp)


def t13_handler(data: dict, ws: ClientConnection) -> None:
    if data:
        if data.get("type") != 13:
            return
    else:
        return
    print(f"meow {json.dumps(data)}")


async def main():
    bot = KirkaChatBot(
        creds.get("token", ""),
        creds.get("refresh_token", ""),
        creds_file="creds.json",
    )
    bot.uri = "wss://local.amcalledglitchy.dev:8765"
    bot.raw_handler = t13_handler
    await bot.listen()


if __name__ == "__main__":
    asyncio.run(main())
