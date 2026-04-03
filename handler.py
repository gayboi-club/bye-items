import json
import logging
import re
from asyncio import Lock
from dataclasses import dataclass
from time import time
from typing import Optional

import aiohttp
from aiohttp import ClientWebSocketResponse

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

TRADE_EXPRESSION = re.compile(
    r".*#([A-Z0-9]{6}) is offering their (.*) for your (.*), type .*/trade accept ([0-9]+).*"
)
ITEM_EXPRESSION = re.compile(
    r"\[([^\[\]|]{1,20})\|([^\[\]|]{0,20})\|([^\[\]|]{1,20})\|([^\[\]|]{1,20})\](x[0-9]+)?"
)
CONFIRM_EXPRESSION = re.compile(r".*your\*\* (.*) for \*\*(.*)'s\*\* (.*)\?.*")
TRADE_TIMEOUT = 0.5

wanted_item_names: list[str] = []
try:
    with open("wanted.json", "r") as fp:
        wanted_item_names = json.load(fp)
    logger.info(f"Loaded {len(wanted_item_names)} wanted items: {wanted_item_names}")
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning(f"Failed to load wanted.json: {e}")


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
        logger.debug(f"Trade state: waiting since {now}")

    async def clear_wait(self):
        """Clear the waiting state. Must be called with lock held."""
        async with self.lock:
            self.waitingSince = None
        logger.debug("Trade state: cleared waiting")

    async def validate_and_return_waiting(self) -> bool:
        """
        Returns True if we're NOT waiting (expired or never set).
        Returns False if we're currently waiting (within timeout).
        """
        now = time()
        async with self.lock:
            if self.waitingSince is None:
                logger.debug("Trade state: not waiting (never set)")
                return True
            elapsed = now - self.waitingSince
            if elapsed >= TRADE_TIMEOUT:
                await self.clear_wait()
                logger.debug(f"Trade state: expired after {elapsed:.3f}s")
                return True
        logger.debug(f"Trade state: still waiting ({elapsed:.3f}s elapsed)")
        return False


TRADE_STATE = TradeState(None, Lock())


def parse_items(raw: str) -> list[KirkaItem]:
    logger.debug(f"Parsing items: {raw!r}")
    split = raw.split(", ")
    items = []
    for i in split:
        match = ITEM_EXPRESSION.match(i)
        if not match:
            logger.debug(f"Item did not match pattern: {i!r}")
            continue
        name, weapon_type, type_, rarity, quantity = match.groups()
        try:
            quantity_int = int(quantity.replace("x", "")) if quantity else 1
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to parse quantity {quantity!r}: {e}")
            quantity_int = 1
        item = KirkaItem(name, weapon_type, type_, rarity, quantity_int)
        logger.debug(f"Parsed item: {item}")
        items.append(item)
    logger.info(f"Total items parsed: {len(items)}")
    return items


def do_we_want_item(item: KirkaItem) -> bool:
    if item.rarity in ["MYTHICAL", "PARANORMAL"]:
        logger.debug(f"Want {item.name} (rarity: {item.rarity})")
        return True
    if item.weapon_type in ["Bayonet", "Tomahawk", "Shark"]:
        logger.debug(f"Want {item.name} (weapon type: {item.weapon_type})")
        return True
    if item.name in wanted_item_names:
        logger.debug(f"Want {item.name} (in wanted list)")
        return True
    logger.debug(f"Don't want {item.name}")
    return False


def can_afford_to_trade(item: KirkaItem) -> bool:
    can_afford = item.name == "Wood" and item.quantity == 1
    logger.debug(f"Can afford {item.name}x{item.quantity}? {can_afford}")
    return can_afford


async def handle_trade(match: re.Match, socket: ClientWebSocketResponse):
    logger.info("=" * 60)
    shortid, their, your, tradeid = match.groups()
    logger.info(f"Trade offer from {shortid} (ID: {tradeid})")
    logger.info(f"  Their items: {their}")
    logger.info(f"  Our items: {your}")

    their_items = parse_items(their)
    your_items = parse_items(your)

    # Check if we can afford
    can_afford_all = all(can_afford_to_trade(i) for i in your_items)
    logger.info(f"Can afford all our items? {can_afford_all}")
    if not can_afford_all:
        logger.info("REJECTING: Cannot afford trade")
        logger.info("=" * 60)
        return

    # Check if we want any
    want_any = any(do_we_want_item(i) for i in their_items)
    logger.info(f"Want any of their items? {want_any}")
    if not want_any:
        logger.info("REJECTING: Don't want their items")
        logger.info("=" * 60)
        return

    logger.info(f"ACCEPTING: yoinking {shortid}'s trade")
    logger.info("=" * 60)
    await accept_trade(tradeid, socket)


async def send_webhook_embed(your_item: str, their_item: str, user_name: str) -> None:
    logger.info(
        f"Sending webhook: we gave {your_item}, got {their_item} from {user_name}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                "https://discord.com/api/webhooks/1489574255942307841/e_Msrt-vp5-eQ4adnqAInjRkjfhOQ7UtvwvkhTQwr6bOzPaG8iCZKU2wbb-ChDnziicy",
                json={
                    "content": "@everyone",
                    "embeds": [
                        {
                            "title": "Trade Confirmed",
                            "color": 0x2ECC71,
                            "fields": [
                                {
                                    "name": "Our",
                                    "value": f"`{your_item}`",
                                    "inline": True,
                                },
                                {
                                    "name": "Their",
                                    "value": f"`{their_item}`",
                                    "inline": True,
                                },
                                {
                                    "name": "happy customer",
                                    "value": f"{user_name}",
                                    "inline": False,
                                },
                            ],
                        }
                    ],
                },
            )
        logger.info("Webhook sent successfully")
    except Exception as e:
        logger.error(f"Webhook failed: {type(e).__name__}: {e}", exc_info=True)


async def handle_type_13(packet: dict, socket: ClientWebSocketResponse) -> None:
    logger.debug(f"Received packet: {packet}")

    if not packet.get("type", 0) == 13:
        logger.debug(f"Ignoring packet type {packet.get('type')}")
        return

    msg: Optional[str] = packet.get("message")
    if msg is None:
        logger.debug("Message is None, ignoring")
        return

    logger.info(f"Message: {msg!r}")

    if msg.startswith("Welcome to a lkchat server"):
        logger.info("Received welcome, sending bot identity")
        try:
            await socket.send_str("name=sniper;level=69;role=BOT")
            logger.debug("Bot identity sent")
        except Exception as e:
            logger.error(f"Failed to send bot identity: {e}", exc_info=True)
        return

    if msg.startswith("You do not have permission to"):
        logger.warning("Permission denied from server")
        logger.debug(f"Full packet: {packet}")
        await TRADE_STATE.clear_wait()
        return

    if msg.startswith("Are you sure you want to"):
        logger.info("Received trade confirmation prompt")
        is_expired = await TRADE_STATE.validate_and_return_waiting()
        logger.info(f"Trade state expired? {is_expired}")

        if not is_expired:
            logger.info("Confirming trade")
            try:
                await socket.send_str("/trade confirm")
                logger.debug("Confirmation sent")
            except Exception as e:
                logger.error(f"Failed to send confirmation: {e}", exc_info=True)

            logger.debug(f"Full confirmation packet: {packet}")
            match = CONFIRM_EXPRESSION.search(msg)
            if match:
                your_item, user_name, their_item = match.groups()
                logger.info(
                    f"Confirmed: {user_name} - we: {your_item}, they: {their_item}"
                )
                await send_webhook_embed(your_item, their_item, user_name)
            else:
                logger.warning("Could not parse confirmation details from message")

            await TRADE_STATE.clear_wait()
        else:
            logger.warning("Confirmation received but trade state expired, ignoring")
        return

    match = TRADE_EXPRESSION.match(msg)
    if match:
        await handle_trade(match, socket)
        return

    logger.debug(f"Message did not match any handler: {msg!r}")


async def accept_trade(id: str, socket: ClientWebSocketResponse):
    logger.info(f"Accepting trade {id}")
    try:
        await socket.send_str(f"/trade accept {id}")
        logger.debug("Accept command sent")
        await TRADE_STATE.set_wait()
    except Exception as e:
        logger.error(f"Failed to accept trade: {e}", exc_info=True)


if __name__ == "__main__":
    # Setup console logging for testing
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    print(parse_items("[Rider||BODY_SKIN|MYTHICAL]x2, [Chilly||BODY_SKIN|MYTHICAL]"))
