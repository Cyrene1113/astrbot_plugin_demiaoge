"""本地 Wiki 的精炼领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WikiEntry:
    category: str
    name: str
    rarity: int
    tags: tuple[str, ...]
    description: str
    skills: tuple[tuple[str, str], ...] = ()
    eidolons: tuple[tuple[str, str], ...] = ()
    aliases: tuple[str, ...] = ()
    version: str = ""

    def searchable_text(self) -> str:
        return " ".join((self.name, *self.aliases, *self.tags)).lower()
