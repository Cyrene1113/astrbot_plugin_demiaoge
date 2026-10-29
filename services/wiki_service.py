"""本地静态 Wiki 查询服务：优先返回最匹配的唯一结果。"""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Sequence

from ..domain.alias_models import AliasTable
from ..domain.wiki_models import WikiEntry


class WikiService:
    def __init__(self, data_file: Path | Sequence[Path], alias_file: Path | None = None) -> None:
        self.entries = self._load(data_file)
        self.aliases = AliasTable.load(alias_file) if alias_file and alias_file.exists() else AliasTable({})

    @staticmethod
    def _load(data_file: Path | Sequence[Path]) -> tuple[WikiEntry, ...]:
        paths = [data_file] if isinstance(data_file, Path) else list(data_file)
        records: list[dict] = []
        for path in paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            if not isinstance(loaded, list):
                raise ValueError(f"Wiki 数据必须是数组：{path}")
            records.extend(item for item in loaded if isinstance(item, dict))
        merged: dict[tuple[str, str], WikiEntry] = {}
        for item in records:
            if "category" not in item or "name" not in item:
                continue
            entry = WikiEntry(
                category=str(item["category"]),
                name=str(item["name"]),
                rarity=int(item.get("rarity", 0)),
                tags=tuple(str(value) for value in item.get("tags", [])),
                description=str(item.get("description", "")),
                skills=tuple((str(x["name"]), str(x["description"])) for x in item.get("skills", []) if isinstance(x, dict) and "name" in x),
                eidolons=tuple((str(x["name"]), str(x["description"])) for x in item.get("eidolons", []) if isinstance(x, dict) and "name" in x),
                aliases=tuple(str(value) for value in item.get("aliases", [])),
                version=str(item.get("version", "")),
            )
            key = (entry.category, entry.name)
            previous = merged.get(key)
            if previous is None or len(entry.skills) + len(entry.eidolons) > len(previous.skills) + len(previous.eidolons):
                merged[key] = entry
        return tuple(merged.values())

    def search(self, keyword: str) -> list[WikiEntry]:
        """返回按名称/别名匹配分数排序的结果，供兼容调用方使用。"""
        return [entry for entry, _ in self._rank(keyword)]

    @staticmethod
    def _words(keyword: str) -> tuple[str, ...]:
        return tuple(part.lower() for part in keyword.strip().split() if part)

    def _rank(self, keyword: str) -> list[tuple[WikiEntry, tuple[int, int, int]]]:
        words = self._words(keyword)
        if not words:
            return []
        ranked: list[tuple[WikiEntry, tuple[int, int, int]]] = []
        for entry in self.entries:
            name = entry.name.lower()
            aliases = tuple(alias.lower() for alias in (*entry.aliases, *self.aliases.for_name(entry.name)))
            name_hits = [name.find(word) for word in words]
            alias_hits = [min((alias.find(word) for alias in aliases if word in alias), default=-1) for word in words]
            if all(hit >= 0 for hit in name_hits):
                score = (3, -sum(name_hits), -sum(len(word) for word in words))
                ranked.append((entry, score))
            elif all(hit >= 0 for hit in alias_hits):
                score = (2, -sum(alias_hits), -sum(len(word) for word in words))
                ranked.append((entry, score))
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def _exact_entry(self, keyword: str) -> WikiEntry | None:
        normalized = keyword.strip().lower()
        for entry in self.entries:
            if entry.name.lower() == normalized:
                return entry
        canonical_name = self.aliases.resolve(keyword)
        for entry in self.entries:
            if entry.name.lower() == canonical_name.lower() or any(alias.lower() == normalized for alias in entry.aliases):
                return entry
        return None

    def _related(self, entry: WikiEntry, keyword: str) -> list[WikiEntry]:
        needle = keyword.strip().lower()
        related = []
        for candidate in self.entries:
            if candidate is entry:
                continue
            haystack = " ".join((*candidate.tags, candidate.description, *candidate.aliases)).lower()
            if needle in haystack:
                related.append(candidate)
        return related[:3]

    @staticmethod
    def format_entry(entry: WikiEntry) -> str:
        lines = [f"【{entry.category}】{entry.name}"]
        if entry.rarity:
            lines.append(f"稀有度：{'★' * entry.rarity}")
        if entry.tags:
            lines.append(f"属性/命途/标签：{'、'.join(entry.tags)}")
        if entry.description:
            lines.append(f"简介：{entry.description}")
        if entry.skills:
            lines.append("技能：")
            lines.extend(f"- {name}：{description}" for name, description in entry.skills)
        if entry.eidolons:
            lines.append("星魂：")
            lines.extend(f"- {name}：{description}" for name, description in entry.eidolons)
        return "\n".join(lines)

    def query(self, keyword: str) -> str:
        exact = self._exact_entry(keyword)
        if exact is not None:
            result = self.format_entry(exact)
            related = self._related(exact, keyword)
            if related:
                result += "\n\n相关：" + "、".join(f"{item.name}（{item.category}）" for item in related)
            return result
        ranked = self._rank(keyword)
        if not ranked:
            return f"没有找到“{keyword.strip()}”的 Wiki 信息。可尝试角色、光锥或遗器名称。"
        if len(ranked) == 1 or ranked[0][1] != ranked[1][1]:
            return self.format_entry(ranked[0][0])
        lines = [f"找到 {len(ranked)} 条结果，请补充名称："]
        lines.extend(f"- {entry.name}（{entry.category}）" for entry, _ in ranked[:20])
        if len(ranked) > 20:
            lines.append(f"（其余 {len(ranked) - 20} 条未显示）")
        return "\n".join(lines)
