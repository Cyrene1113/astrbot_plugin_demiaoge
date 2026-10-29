"""将已抓取的 HSR Wiki 原始 JSON 转为插件 WikiEntry 数据。

只读工作区中的已有文件，不发起网络请求。
运行（在插件目录执行）：
    python scripts/convert_wiki.py
可选：
    python scripts/convert_wiki.py --source C:\\Users\\14476\\.astrbot\\data\\workspaces\\_FriendMessage_1447653277\\hsr_wiki_data
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path(r"C:\Users\14476\.astrbot\data\workspaces\_FriendMessage_1447653277\hsr_wiki_data")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def rarity(value: Any) -> int:
    match = re.search(r"([1-6])", text(value))
    return int(match.group(1)) if match else 0


def split_values(value: Any) -> list[str]:
    raw = text(value)
    return [part.strip() for part in re.split(r"[,，、/|]", raw) if part.strip()]


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def scalar(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = text(data.get(key))
        if value and not value.startswith("<!--"):
            return value
    return ""


def walk_pairs(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """从不同版本的技能/星魂嵌套结构中提取名称和描述。"""
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        name = scalar(value, "名称", "技能名称", "星魂名称", "name", "title")
        desc = scalar(value, "描述", "技能描述", "效果", "description")
        if desc:
            found.append(("·".join(x for x in (prefix, name) if x) or "效果", desc))
        for key, child in value.items():
            if key not in {"名称", "技能名称", "星魂名称", "name", "title", "描述", "技能描述", "效果", "description"}:
                found.extend(walk_pairs(child, "·".join(x for x in (prefix, text(key)) if x)))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_pairs(child, prefix))
    return found


def pairs_to_items(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, desc in pairs:
        item = (name, desc)
        if desc and item not in seen:
            result.append({"name": name, "description": desc})
            seen.add(item)
    return result


def role_record(item: dict[str, Any]) -> dict[str, Any]:
    base = item.get("base") if isinstance(item.get("base"), dict) else {}
    skills = item.get("skills", {})
    name = scalar(base, "名称") or text(item.get("name")) or text(item.get("title"))
    tags = unique([scalar(base, "元素属性"), scalar(base, "命途")])
    description = scalar(base, "角色定位", "介绍", "描述")
    aliases = unique(split_values(scalar(base, "昵称/外号", "昵称", "外号")))

    # 角色技能模板的真实结构是：技能类型 -> {类型, 名称, 描述...}。
    # 不再把“未加强·”拼进名称，而是输出稳定的 type/name/description 字段。
    skill_items: list[dict[str, str]] = []
    eidolons: list[dict[str, str]] = []
    selected = skills.get("未加强") if isinstance(skills, dict) else None
    if not isinstance(selected, dict) and isinstance(skills, dict):
        selected = skills.get("加强")
    if isinstance(selected, dict):
        for key, value in selected.items():
            if key == "星魂" and isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        ename = scalar(entry, "名称", "星魂名称", "name", "title")
                        edesc = scalar(entry, "描述", "技能描述", "效果", "description", "desc")
                        if ename or edesc:
                            eidolons.append({"name": ename, "description": edesc})
                continue
            if key in {"额外能力", "属性加成"}:
                entries = value if isinstance(value, list) else []
                for entry in entries:
                    if isinstance(entry, dict):
                        ename = scalar(entry, "名称", "name", "title", "属性")
                        edesc = scalar(entry, "描述", "效果", "description", "desc", "数值")
                        if ename or edesc:
                            skill_items.append({"type": key, "name": ename, "description": edesc})
                continue
            if not isinstance(value, dict):
                continue
            skill_name = scalar(value, "名称", "技能名称", "name", "title")
            skill_desc = scalar(value, "描述", "技能描述", "效果", "description")
            skill_type = scalar(value, "类型", "type") or key
            if skill_name or skill_desc:
                skill_items.append({"type": skill_type, "name": skill_name, "description": skill_desc})

    # 兼容旧汇总数据中单独保存的 eidolons 字段及极少数旧角色的 base 字段。
    if not eidolons:
        eidolon_source = {key: value for key, value in base.items() if "星魂" in key or "命途回响" in key}
        eidolons = [{"name": n, "description": d} for n, d in walk_pairs(eidolon_source)]
    if not eidolons:
        eidolons = [{"name": n, "description": d} for n, d in walk_pairs(item.get("eidolons", {}))]
    return {"category": "角色", "name": name, "rarity": rarity(base.get("稀有度")), "tags": tags,
            "description": description, "skills": skill_items, "eidolons": eidolons,
            "aliases": aliases, "version": scalar(base, "实装版本")}


def item_record(item: dict[str, Any], category: str) -> dict[str, Any]:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    name = scalar(data, "名称") or text(item.get("name")) or text(item.get("title"))
    tags = unique([scalar(data, "命途"), scalar(data, "属性", "元素属性")])
    description = scalar(data, "介绍", "描述", "效果", "套装效果", "两件套", "四件套")
    if category == "遗器":
        effects = [text(value) for key, value in data.items() if "套" in key or "效果" in key]
        description = "\n".join(unique(effects)) or description
    skill_pairs: list[tuple[str, str]] = []
    if category == "光锥":
        # 模板字段是“技能名称/技能效果”，不能只匹配“技能”后再读取占位参数。
        skill_name = scalar(data, "技能名称")
        skill_desc = scalar(data, "技能效果")
        if skill_name and skill_name not in {"技能名称", "技能名"} and skill_desc and skill_desc not in {"假设", "技能效果"}:
            skill_pairs.append((skill_name, skill_desc))
    else:
        for key, value in data.items():
            if any(word in key for word in ("技能", "效果", "套装", "被动")) and text(value):
                skill_pairs.append((text(key), text(value)))
    return {"category": category, "name": name, "rarity": rarity(data.get("稀有度")), "tags": tags,
            "description": description, "skills": pairs_to_items(skill_pairs), "eidolons": [],
            "aliases": [], "version": scalar(data, "实装版本")}


def load(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="转换本地已抓取的 Wiki 数据，不联网")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = parser.parse_args()
    specs = [("roles.json", "characters.json", "角色", role_record),
             ("light_cones.json", "light_cones.json", "光锥", lambda x: item_record(x, "光锥")),
             ("relics.json", "relics.json", "遗器", lambda x: item_record(x, "遗器"))]
    args.output.mkdir(parents=True, exist_ok=True)
    for source_name, output_name, _category, converter in specs:
        records = [converter(item) for item in load(args.source / source_name)]
        (args.output / output_name).write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {output_name}: {len(records)} 条")


if __name__ == "__main__":
    main()
