"""BiliGame Wiki 增量爬取器。

只使用标准库；原始页面按类别和 pageid 缓存，解析失败不会覆盖上一次产物。
完整更新：``python -m services.wiki_crawler``；仅重解析缓存：``--parse-only``。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://wiki.biligame.com/sr/api.php"
CATEGORIES = {
    "roles": ("模板:角色图鉴", "角色图鉴"),
    "light_cones": ("模板:光锥图鉴", "光锥图鉴"),
    "relics": ("模板:遗器套装", "遗器套装"),
}
LOG = logging.getLogger(__name__)


def split_top_level(value: str, separator: str) -> list[str]:
    result, current, depth, index = [], [], 0, 0
    while index < len(value):
        pair = value[index:index + 2]
        if pair == "{{":
            depth += 1; current.append(pair); index += 2
        elif pair == "}}":
            depth = max(0, depth - 1); current.append(pair); index += 2
        elif value[index] == separator and depth == 0:
            result.append("".join(current)); current = []; index += 1
        else:
            current.append(value[index]); index += 1
    result.append("".join(current))
    return result


def parse_templates(text: str) -> list[tuple[str, dict[str, str]]]:
    found, index = [], 0
    while index < len(text) - 1:
        if text[index:index + 2] != "{{":
            index += 1; continue
        depth, end = 1, index + 2
        while end < len(text) - 1 and depth:
            if text[end:end + 2] == "{{": depth += 1; end += 2
            elif text[end:end + 2] == "}}": depth -= 1; end += 2
            else: end += 1
        if depth:
            break
        parts = split_top_level(text[index + 2:end - 2], "|")
        # 模板名可能携带 HTML 注释（如“光锥图鉴<!-- 备注 -->”），剥离后再匹配。
        name = re.sub(r"<!--.*?-->", "", parts[0]).strip()
        params = {}
        for part in parts[1:]:
            if "=" in part:
                key, item = part.split("=", 1)
                if key.strip(): params[key.strip()] = item.strip()
        found.append((name, params)); index = end
    return found


def clean(value: Any) -> str:
    text = str(value or "").strip()
    for _ in range(5):
        updated = re.sub(r"\{\{(.+?)\}\}", lambda m: split_top_level(m.group(1), "|")[-1].strip(), text, flags=re.S)
        if updated == text: break
        text = updated
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


class WikiCrawler:
    def __init__(self, output_dir: Path, delay: float = 1.2, retries: int = 5) -> None:
        self.output_dir, self.raw_dir = output_dir, output_dir / "raw"
        self.delay, self.retries = delay, retries
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.logger = LOG

    def request(self, params: dict[str, str]) -> dict[str, Any] | None:
        url = API + "?" + urlencode(params)
        for attempt in range(self.retries):
            try:
                request = Request(url, headers={"User-Agent": "DemiaogeWiki/1.0", "Referer": "https://wiki.biligame.com/sr/"})
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # 网络波动和限流由重试处理
                self.logger.warning("请求失败 %s/%s: %s", attempt + 1, self.retries, exc)
                time.sleep(min(30.0, self.delay * (attempt + 1)))
        return None

    def pages(self, template: str) -> list[tuple[int, str]]:
        result, continuation = [], {}
        while True:
            params = {"action": "query", "list": "embeddedin", "eititle": template, "eilimit": "500", "format": "json", "formatversion": "2", **continuation}
            payload = self.request(params)
            if not payload: break
            result.extend((int(item["pageid"]), item["title"]) for item in payload.get("query", {}).get("embeddedin", []) if item.get("ns") == 0)
            if "continue" not in payload: break
            continuation = payload["continue"]
        return result

    def fetch(self, category: str, pageid: int, title: str) -> dict[str, Any] | None:
        target = self.raw_dir / f"{category}_{pageid}.json"
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8"))
        payload = self.request({"action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": "2"})
        if not payload or "parse" not in payload: return None
        raw = {"pageid": pageid, "title": title, "data": payload}
        target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        time.sleep(self.delay)
        return raw

    def parse(self, category: str, raw: dict[str, Any], template: str) -> dict[str, Any] | None:
        text = raw.get("data", {}).get("parse", {}).get("wikitext", "")
        if isinstance(text, dict): text = text.get("*", "")
        candidates = [(name, params) for name, params in parse_templates(text) if name == template]
        if not candidates: return None
        params = {key: clean(value) for key, value in candidates[0][1].items()}
        # 部分模板用 {{PAGENAME}} 魔法字代替字面名称，此时回退到页面标题。
        name = params.get("名称") or raw.get("title", "")
        if name == "PAGENAME" or "{{PAGENAME}}" in name:
            name = raw.get("title", name)
        if category == "roles":
            skills = []
            for key in ("普攻", "战技", "终结技", "天赋", "秘技"):
                if params.get(key): skills.append({"name": key, "description": clean(params[key])})
            return {"name": name, "pageid": raw.get("pageid"), "title": raw.get("title"), "base": params, "skills": skills}
        return {"name": name, "pageid": raw.get("pageid"), "title": raw.get("title"), "data": params}

    def run(self, parse_only: bool = False) -> dict[str, int]:
        counts = {}
        for category, (embedded, template) in CATEGORIES.items():
            raws = []
            if parse_only:
                raws = [json.loads(path.read_text(encoding="utf-8")) for path in self.raw_dir.glob(f"{category}_*.json")]
            else:
                for pageid, title in self.pages(embedded):
                    raw = self.fetch(category, pageid, title)
                    if raw: raws.append(raw)
            records = [item for raw in raws if (item := self.parse(category, raw, template))]
            records.sort(key=lambda item: item.get("name", ""))
            output = self.output_dir / f"{category}.json"
            temporary = output.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(output)
            counts[category] = len(records)
            self.logger.info("%s: %d 条", category, len(records))
        return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "wiki_source")
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--delay", type=float, default=1.2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(WikiCrawler(args.output, args.delay).run(args.parse_only))


if __name__ == "__main__": main()
