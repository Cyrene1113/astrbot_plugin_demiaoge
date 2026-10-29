"""从当前 BWiki API 全量重建插件正式 Wiki 数据。

唯一来源是 wiki.biligame.com/sr/api.php 的 Category:... namespace=0 目录及
对应 parse 页面。正式 JSON 不与旧数据合并；每个类别完成后通过临时文件原子替换。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import secrets
import socket
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://wiki.biligame.com/sr/api.php"
ALLOWED_HOSTS = {"wiki.biligame.com"}

# 禁重定向 opener：SSRF 防护的一部分（防止白名单域名 30x 跳去别处）。
_opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())


def _safe_url(url: str) -> str:
    """SSRF 防护：仅允许 https + 域名白名单，且解析出的 IP 不得为私网/环回/链路本地。

    fetch_wiki 的请求目标固定为 BWiki API；该检查保证即便拼接参数被改动，
    也不会把请求引向内网、云元数据或本机服务。
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"拒绝非白名单请求目标: {url}")
    for info in socket.getaddrinfo(parsed.hostname, 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"域名解析到受限地址 {ip}，拒绝请求")
    return url

CATEGORIES = {
    "角色": ("Category:角色", "characters.json", ("角色图鉴",)),
    "光锥": ("Category:光锥", "light_cones.json", ("光锥图鉴",)),
    "遗器": ("Category:遗器", "relics.json", ("遗器图鉴", "遗器套装")),
}
PLACEHOLDERS = {"", "PAGENAME", "需要内容", "待补充", "暂无", "占位"}


def request_json(params: dict[str, str], retries: int = 4) -> tuple[dict[str, Any] | None, str | None]:
    url = _safe_url(API + "?" + urlencode(params))
    last = ""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "DemiaogeWiki/2.0 (+https://astrbot.app)"})
            with _opener.open(req, timeout=35) as response:
                return json.loads(response.read().decode("utf-8")), None
        except Exception as exc:
            last = repr(exc)
            if attempt + 1 < retries:
                # 指数退避（上限 25s）：WAF 限频/瞬断需要更长冷却窗口。
                time.sleep(min(25.0, 2.5 * (attempt + 1) * (attempt + 1)))
    return None, last


def category_pages(category: str) -> list[str]:
    titles: list[str] = []
    cont: dict[str, str] = {}
    while True:
        payload, error = request_json({
            "action": "query", "list": "categorymembers", "cmtitle": category,
            "cmnamespace": "0", "cmlimit": "500", "format": "json", **cont,
        })
        if payload is None:
            raise RuntimeError(f"目录请求失败 {category}: {error}")
        for item in payload.get("query", {}).get("categorymembers", []):
            if item.get("ns") == 0 and isinstance(item.get("title"), str):
                titles.append(item["title"])
        continuation = payload.get("continue")
        if not continuation:
            break
        cont = {key: str(value) for key, value in continuation.items() if key != "continue"}
        if "continue" in continuation:
            cont["continue"] = str(continuation["continue"])
    return list(dict.fromkeys(titles))


def templates(text: str) -> list[str]:
    found, start = [], 0
    while True:
        begin = text.find("{{", start)
        if begin < 0:
            return found
        depth, index = 1, begin + 2
        while index < len(text) - 1 and depth:
            if text[index:index + 2] == "{{":
                depth += 1; index += 2
            elif text[index:index + 2] == "}}":
                depth -= 1; index += 2
            else:
                index += 1
        if depth:
            return found
        found.append(text[begin + 2:index - 2])
        start = index


def split_fields(body: str) -> tuple[str, dict[str, str]]:
    parts, current, depth = [], [], 0
    index = 0
    while index < len(body):
        pair = body[index:index + 2]
        if pair == "{{":
            depth += 1; current.extend(pair); index += 2
        elif pair == "}}":
            depth = max(0, depth - 1); current.extend(pair); index += 2
        elif body[index] == "|" and depth == 0:
            parts.append("".join(current)); current = []; index += 1
        else:
            current.append(body[index]); index += 1
    parts.append("".join(current))
    values: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            if key.strip(): values[key.strip()] = clean(value)
    return parts[0].strip(), values


def clean(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # 内联模板处理：{{颜色|a|b}}/{{效果说明|b}} 保留展示文本（末参），
    # 其余（#info 等无展示文本的模板）删除——逐层剥到无花括号为止。
    def _keep_last_param(match: re.Match[str]) -> str:
        params = match.group(1).split("|")
        return params[-1].strip() if len(params) >= 2 else ""
    for _ in range(6):
        updated = re.sub(r"\{\{([^{}]*)\}\}", _keep_last_param, text)
        if updated == text:
            break
        text = updated
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_page(category: str, title: str, text: str) -> tuple[dict[str, Any] | None, str | None]:
    markers = CATEGORIES[category][2]
    candidates = []
    for raw in templates(text):
        name, values = split_fields(raw)
        if any(marker in name for marker in markers):
            candidates.append(values)
    title = title.strip()
    if not title or title in PLACEHOLDERS or title.startswith("模板:"):
        return None, "空标题或占位标题"
    if not candidates:
        return None, "未找到对应图鉴模板"
    data = candidates[0]
    # 页面标题是唯一规范主键；PAGENAME/模板名称绝不进入正式 name。
    name = title
    rarity_match = re.search(r"([1-6])", data.get("稀有度", ""))
    tag_keys = ("元素属性", "命途", "属性", "类型", "光锥TAG", "TAG")
    tags = [data.get(key, "") for key in tag_keys]
    tags = [value for value in tags if value and value not in PLACEHOLDERS]
    if category == "遗器":
        desc = "\n".join(dict.fromkeys(value for key, value in data.items() if ("套" in key or "效果" in key) and value))
    elif category == "光锥":
        # BWiki 光锥模板：风味文本在「光锥故事」，技能在 技能名称/技能效果。
        desc = data.get("光锥故事") or data.get("介绍") or data.get("描述") or data.get("效果", "")
    else:
        # BWiki 角色模板：一句话定位在「角色定位」，详细文本在「角色详细」；
        # 「介绍」多数留空（仅与角色详情不同时才填），故放最后。
        desc = (data.get("角色定位") or data.get("角色详细")
                or data.get("介绍") or data.get("描述") or data.get("效果", ""))
    skills = []
    for key in ("普攻", "战技", "终结技", "天赋", "秘技", "技能效果", "两件套效果", "四件套效果"):
        if data.get(key) and data[key] not in PLACEHOLDERS:
            skills.append({"name": key, "description": data[key]})
    if category == "光锥" and data.get("技能名称") and data.get("技能效果"):
        skills = [{"name": data["技能名称"], "description": data["技能效果"]}]
    eidolons = _character_eidolons(text) if category == "角色" else []
    trace_skills = _character_trace_skills(text) if category == "角色" else []
    if trace_skills:
        # 页内嵌的 行迹/技能（含名称+描述）比模板顶层键完整，优先采用。
        skills = trace_skills
    return {
        "category": category, "name": name,
        "rarity": int(rarity_match.group(1)) if rarity_match else 0,
        "tags": list(dict.fromkeys(tags)), "description": desc, "skills": skills,
        "eidolons": eidolons, "aliases": [], "version": data.get("实装版本", ""),
    }, None


CHARACTER_SKILL_TEMPLATES = ("角色/技能", "角色图鉴/技能")  # 新角色页 / 旧角色页两代模板


def _skill_template_bodies(page_text: str) -> list[tuple[str, str]]:
    """收集角色技能模板的 (模板名, 原始体)。

    三种布局：①顶层 `{{角色/技能}}`；②顶层旧版 `{{角色图鉴/技能}}`；
    ③嵌套在 `{{角色/加强|未加强={{角色/技能|...}}}}` 内（加强前后各一份，取首份）。
    """
    bodies: list[tuple[str, str]] = []
    for raw in templates(page_text):
        head = split_fields(raw)[0].strip()
        if head in CHARACTER_SKILL_TEMPLATES:
            bodies.append((head, raw))
    if not any(name == "角色/技能" for name, _ in bodies):
        for raw in _nested_templates(page_text, "角色/技能"):
            head = split_fields(raw)[0].strip()
            if head == "角色/技能":
                bodies.append(("角色/技能", raw))
    return bodies


def _character_eidolons(page_text: str) -> list[dict[str, str]]:
    """从技能模板提取星魂1-6（名称+描述）；两代模板同构，缺失项静默跳过。"""
    for template_name, raw in _skill_template_bodies(page_text):
        _, values = split_fields(raw)
        eidolons = []
        for index in range(1, 7):
            title = values.get(f"星魂{index}", "")
            desc = values.get(f"星魂{index}描述", "")
            if title and title not in PLACEHOLDERS and desc:
                eidolons.append({"name": title, "description": desc})
        if eidolons:
            return eidolons
    return []


def _character_trace_skills(page_text: str) -> list[dict[str, str]]:
    """提取角色技能（类型·名称 + 描述）。

    - 新模板 `角色/技能`（含嵌套于 角色/加强 内的实例）：技能在体内嵌套的
      `{{行迹/技能}}`（类型/名称/描述）。注意不能用 split_fields 的字段值：
      clean() 会把嵌套模板剥掉；必须扫原始体。
    - 旧模板 `角色图鉴/技能`：技能在顶层键 普攻/战技/终结技/天赋/秘技（名称）+
      `{键}描述`（描述）。
    """
    for template_name, raw in _skill_template_bodies(page_text):
        if template_name == "角色图鉴/技能":
            _, values = split_fields(raw)
            skills = []
            for key in ("普攻", "战技", "终结技", "天赋", "秘技"):
                title = values.get(key, "")
                desc = values.get(f"{key}描述", "")
                if title and title not in PLACEHOLDERS and desc and desc not in PLACEHOLDERS:
                    skills.append({"name": f"{key}·{title}", "description": desc})
            if skills:
                return skills
            continue
        skills = []
        seen: set[str] = set()
        for body in _nested_templates(raw, "行迹/技能"):
            _, nested_values = split_fields(body)
            kind = nested_values.get("类型", "")
            title = nested_values.get("名称", "")
            desc = nested_values.get("描述", "")
            if not title or not desc or title in PLACEHOLDERS:
                continue
            display = f"{kind}·{title}" if kind and kind not in PLACEHOLDERS else title
            if display in seen:
                continue
            seen.add(display)
            skills.append({"name": display, "description": desc})
        if skills:
            return skills
    return []


def _nested_templates(text: str, template_name: str) -> list[str]:
    """提取文本中所有名为 template_name 的平衡模板体（含跨行嵌套）。"""
    found: list[str] = []
    marker = "{{" + template_name
    index = 0
    while True:
        begin = text.find(marker, index)
        if begin < 0:
            return found
        tail = text[begin + len(marker):begin + len(marker) + 1]
        if tail and tail not in ("\n", "\r", "\t", " ", "|", "}"):
            index = begin + len(marker)  # 名字前缀撞车（如 行迹/技能X），跳过
            continue
        depth, cursor = 1, begin + 2
        while cursor < len(text) - 1 and depth:
            if text[cursor:cursor + 2] == "{{":
                depth += 1; cursor += 2
            elif text[cursor:cursor + 2] == "}}":
                depth -= 1; cursor += 2
            else:
                cursor += 1
        if depth == 0:
            found.append(text[begin + 2:cursor - 2])
        index = cursor


def fetch_one(item: tuple[str, str]) -> tuple[str, dict[str, Any] | None, str | None]:
    category, title = item
    # 随机抖动（secrets 源）：避免固定节奏触发 BWiki WAF 限频（实测会返回非标准 567）。
    time.sleep(0.8 + (secrets.randbelow(1000) / 1000.0))
    payload, error = request_json({"action": "parse", "page": title, "prop": "wikitext", "format": "json"})
    if payload is None:
        return title, None, f"页面请求失败: {error}"
    parsed = payload.get("parse", {}).get("wikitext", "")
    text = parsed.get("*", "") if isinstance(parsed, dict) else str(parsed)
    if not text:
        return title, None, "页面无 wikitext"
    record, reason = parse_page(category, title, text)
    return title, record, reason


def atomic_write(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".sync.tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_record(record: dict[str, Any]) -> str | None:
    """入库前机械校验；返回 None 表示通过，否则为剔除原因。

    清理目标：占位标题（PAGENAME/需要内容 等）、非法星级、正文与技能全空的空白页。
    星级=0 允许存在（NPC/未实装资料页、遗器套装模板无星级字段），但必须有正文。
    """
    name = str(record.get("name", "")).strip()
    if not name or name in PLACEHOLDERS or "需要内容" in name or "PAGENAME" in name:
        return "占位或空名称"
    rarity = int(record.get("rarity", 0) or 0)
    if rarity != 0 and not 3 <= rarity <= 6:
        return "星级非法"
    has_desc = bool(str(record.get("description", "")).strip())
    has_skills = any(str(item.get("description", "")).strip() for item in record.get("skills", []))
    has_eidolons = any(str(item.get("description", "")).strip() for item in record.get("eidolons", []))
    if not (has_desc or has_skills or has_eidolons):
        return "描述/技能/星魂全空"
    if rarity == 0 and not (has_desc or has_skills):
        return "零星且缺正文"
    return None


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同名条目保留内容最丰富的一条（描述+技能+星魂字数与条数合计）。"""

    def richness(item: dict[str, Any]) -> tuple[int, int]:
        filled = sum(len(str(item.get("description", ""))))
        filled += sum(len(str(skill.get("description", ""))) for skill in item.get("skills", []))
        filled += sum(len(str(item.get("description", ""))) for item in item.get("eidolons", []))
        return filled, len(item.get("skills", [])) + len(item.get("eidolons", []))

    best: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("name", ""))
        current = best.get(key)
        if current is None or richness(record) > richness(current):
            best[key] = record
    return sorted(best.values(), key=lambda item: item["name"])


def run(categories: list[str], workers: int) -> None:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    audit: dict[str, Any] = {"source": API, "categories": {}}
    for category in categories:
        category_api, filename, _ = CATEGORIES[category]
        titles = category_pages(category_api)
        # 目录已经限制 namespace=0；再次过滤占位和模板页并记录过滤数量。
        valid_titles = [title for title in titles if title.strip() and title.strip() not in PLACEHOLDERS and not title.startswith("模板:")]
        filtered = len(titles) - len(valid_titles)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_one, (category, title)) for title in valid_titles]
            for future in as_completed(futures):
                title, record, reason = future.result()
                if record is not None:
                    records.append(record)
                else:
                    failures.append({"title": title, "reason": reason or "未知解析失败"})
        dropped = []
        kept: list[dict[str, Any]] = []
        for record in records:
            reason = validate_record(record)
            if reason is None:
                kept.append(record)
            else:
                dropped.append({"name": record.get("name", ""), "reason": reason})
        kept = dedupe(kept)
        atomic_write(data_dir / filename, kept)
        audit["categories"][category] = {
            "directory_titles": len(titles), "filtered_titles": filtered,
            "valid_titles": len(valid_titles), "parsed_success": len(records),
            "parsed_failure": len(failures), "failures": sorted(failures, key=lambda x: x["title"]),
            "dropped_invalid": sorted(dropped, key=lambda x: x["name"]),
            "kept_after_cleanup": len(kept),
            "local_file": filename,
        }
        print(f"[{category}] 目录={len(titles)} 有效={len(valid_titles)} 成功={len(records)} "
              f"剔除={len(dropped)} 失败={len(failures)} 入库={len(kept)}", flush=True)
    atomic_write(data_dir / "wiki_sync_audit.json", audit)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", nargs="+", choices=list(CATEGORIES), default=list(CATEGORIES))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    run(args.categories, max(1, min(args.workers, 6)))


if __name__ == "__main__":
    main()
