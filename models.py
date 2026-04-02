
from dataclasses import dataclass
from enum import Enum


class Rarity(Enum):



@dataclass
class TradeItem:
    name: str
    weaponName: str
    skinType: str
    rarity: str
