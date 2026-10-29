"""本地 Wiki 别名表模型。"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class AliasTable:
    """维护黑话/外号/英文名到规范名称的映射。"""

    mappings: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "AliasTable":
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        return cls({str(alias).lower(): str(name) for alias, name in data.items()})

    def resolve(self, alias: str) -> str:
        return self.mappings.get(alias.strip().lower(), alias.strip())

    def for_name(self, name: str) -> tuple[str, ...]:
        normalized = name.strip().lower()
        return tuple(alias for alias, target in self.mappings.items() if target.lower() == normalized)
