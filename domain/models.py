"""不依赖 AstrBot/外部 API 的角色领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CharacterSummary:
    name: str
    level: int
    eidolons: int
    rarity: int = 5


@dataclass(frozen=True)
class PlayerProfile:
    uid: str
    nickname: str
    level: int
    characters: tuple[CharacterSummary, ...]
