import re
from dataclasses import dataclass
from typing import Optional

from websockets import ClientConnection

TRADE_EXPRESSION = re.compile(
    r".*#([A-Z0-9]{6}).*their\s+(.*)your\s+(.*).*\/trade accept ([0-9]+).*"
)
ITEM_EXPRESSION = re.compile(
    r"\[([^\[\]|]{1,20})\|([^\[\]|]{0,20})\|([^\[\]|]{1,20})\|([^\[\]|]{1,20})\]"
)


async def handle_type_13(packet: dict, socket: ClientConnection) -> None:
    msg: Optional[str] = packet.get("message")
    if not msg:
        return

    match = TRADE_EXPRESSION.match(msg)
    if not match:
        return

    shortid, their, your, tradeid = match.groups()
