import asyncio

from kirkaio import KirkaChatBot

from handler import handle_type_13


async def main():
    bot = KirkaChatBot(
        creds_file="creds.json",
    )
    bot.uri = "wss://local.amcalledglitchy.dev:8765"
    bot.raw_handler = handle_type_13
    await bot.listen()


if __name__ == "__main__":
    asyncio.run(main())
