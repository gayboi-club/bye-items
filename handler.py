import json
import re
from asyncio import Lock
from dataclasses import dataclass
from time import time
from typing import Optional

from aiohttp import ClientWebSocketResponse

TRADE_EXPRESSION = re.compile(
    r".*#([A-Z0-9]{6}) is offering their (.*) for your (.*), type .*/trade accept ([0-9]+).*"
)
ITEM_EXPRESSION = re.compile(
    r"\[([^\[\]|]{1,20})\|([^\[\]|]{0,20})\|([^\[\]|]{1,20})\|([^\[\]|]{1,20})\](x[0-9]+)?"
)
TRADE_TIMEOUT = 0.5

wanted_item_names: list[str] = []
try:
    with open("wanted.json", "r") as fp:
        wanted_item_names = json.load(fp)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"json fail {e}")


@dataclass
class KirkaItem:
    name: str
    weapon_type: Optional[str]
    type: str
    rarity: str
    quantity: int = 1


@dataclass
class TradeState:
    waitingSince: Optional[float]
    lock: Lock

    async def set_wait(self):
        now = time()
        async with self.lock:
            self.waitingSince = now

    async def clear_wait(self):
        """Clear the waiting state. Must be called with lock held."""
        self.waitingSince = None

    async def validate_and_return_waiting(self) -> bool:
        """
        Returns True if we're NOT waiting (expired or never set).
        Returns False if we're currently waiting (within timeout).
        """
        now = time()
        async with self.lock:
            if self.waitingSince is None:
                return True
            if now - self.waitingSince >= TRADE_TIMEOUT:
                await self.clear_wait()
                return True
        return False


TRADE_STATE = TradeState(None, Lock())


def parse_items(raw: str) -> list[KirkaItem]:
    split = raw.split(", ")
    items = []
    for i in split:
        match = ITEM_EXPRESSION.match(i)
        if not match:
            continue
        name, weapon_type, type_, rarity, quantity = match.groups()
        try:
            quantity_int = int(quantity.replace("x", "")) if quantity else 1
        except (TypeError, ValueError):
            quantity_int = 1
        items.append(KirkaItem(name, weapon_type, type_, rarity, quantity_int))
    return items


def do_we_want_item(item: KirkaItem) -> bool:
    if item.rarity in ["MYTHICAL", "PARANORMAL"]:
        return True
    if item.weapon_type in ["Bayonet", "Tomahawk", "Shark"]:
        return True
    if item.name in wanted_item_names:
        return True
    return False


def can_afford_to_trade(item: KirkaItem) -> bool:
    if item.name == "Wood" and item.quantity == 1:
        return True
    return False


async def handle_trade(match: re.Match, socket: ClientWebSocketResponse):
    shortid, their, your, tradeid = match.groups()
    their_items = parse_items(their)
    your_items = parse_items(your)

    if not all(can_afford_to_trade(i) for i in your_items):
        return
    if not any(do_we_want_item(i) for i in their_items):
        return

    print(f"yoinking {shortid}'s trade, their {their} for our {your}, id {tradeid}")
    await accept_trade(tradeid, socket)


async def handle_type_13(packet: dict, socket: ClientWebSocketResponse) -> None:
    msg: Optional[str] = packet.get("message")
    if msg is None:
        return

    if msg.startswith("Welcome to a lkchat server"):
        await socket.send_str("name=sniper;level=69;role=BOT")
        return

    if msg.startswith("You do not have permission to"):
        print("consent is apparently needed", packet)
        await TRADE_STATE.clear_wait()
        return

    if msg.startswith("Are you sure you want to"):
        if await TRADE_STATE.validate_and_return_waiting():
            await socket.send_str("/trade confirm")
            print("wait i think we yoinked smth", packet)
            await TRADE_STATE.clear_wait()
        return

    match = TRADE_EXPRESSION.match(msg)
    if match:
        await handle_trade(match, socket)
        return


async def accept_trade(id: str, socket: ClientWebSocketResponse):
    await socket.send_str(f"/trade accept {id}")
    await TRADE_STATE.set_wait()


if __name__ == "__main__":
    print(parse_items("[Rider||BODY_SKIN|MYTHICAL]x2, [Chilly||BODY_SKIN|MYTHICAL]"))
