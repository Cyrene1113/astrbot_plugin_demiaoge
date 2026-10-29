"""Wiki 数据周期核对服务（W6）：每日固定时间与 BWiki 线上目录核对并增量入库。

职责（全机械，无 LLM）：
- ``run_sync_once()``：调 ``scripts/fetch_wiki.run``（同步阻塞，调用方须 to_thread）
  全量拉取三类目录 → 解析 → 校验清洗 → 与本地旧数据核对出差异 → 原子写盘 → 审计报告。
  任一类别目录请求失败：保留本地旧文件（fetch_wiki 按类别各自原子替换，失败的类别不写盘）。
- ``diff_report()``：新旧记录按 (category, name) 对比，输出新增/移除/内容更新清单。
- ``schedule_loop()``：每日 ``HH:MM`` 触发一次 ``run_sync_once``，循环等待下一个时间点；
  取消安全（asyncio.CancelledError 直接退出）。

爬取节奏：fetch_wiki 内置 0.8-1.8s 随机抖动 + 指数退避；workers 建议不超过 3，
避免触发 BWiki WAF（实测会返回非标准 567）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..scripts import fetch_wiki

LOGGER = logging.getLogger("demiaoge.wiki_sync")


class WikiUpdateService:
    """每日定时核对 BWiki 与本地 Wiki 数据；核对结果落审计文件。"""

    def __init__(self, data_dir: Path, daily_time: str = "04:30",
                 workers: int = 3, audit_name: str = "wiki_sync_audit.json") -> None:
        self._data_dir = Path(data_dir)
        self._workers = max(1, min(int(workers), 6))
        self._audit_name = audit_name
        self.hour, self.minute = self.parse_daily_time(daily_time)
        self.last_report: dict[str, Any] | None = None

    # ---------- 配置解析 ----------

    @staticmethod
    def parse_daily_time(text: str) -> tuple[int, int]:
        """解析 "HH:MM"；非法输入回退 04:30（机械兜底，不抛异常）。"""
        parts = str(text or "").strip().split(":")
        try:
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
        except (ValueError, IndexError, TypeError):
            pass
        return 4, 30

    # ---------- 核对与入库 ----------

    def _snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        """读取本地三类 JSON → {category: {name: record}}（解析失败视为空）。"""
        snapshot: dict[str, dict[str, dict[str, Any]]] = {}
        for category, (__, filename, ___) in fetch_wiki.CATEGORIES.items():
            path = self._data_dir / filename
            records: list[dict[str, Any]] = []
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        records = [item for item in loaded if isinstance(item, dict)]
                except (json.JSONDecodeError, OSError):
                    records = []
            snapshot[category] = {str(item.get("name", "")): item for item in records}
        return snapshot

    @staticmethod
    def _richness(record: dict[str, Any]) -> int:
        desc = len(str(record.get("description", "")))
        skills = sum(len(str(item.get("description", ""))) for item in record.get("skills", []))
        eidolons = sum(len(str(item.get("description", ""))) for item in record.get("eidolons", []))
        return desc + skills + eidolons

    def diff_report(self, before: dict[str, dict[str, dict[str, Any]]],
                    after: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
        """新旧按 (category, name) 机械对比：新增/移除/内容变化（本地更丰富则不视为更新）。"""
        report: dict[str, Any] = {}
        for category, old_items in before.items():
            new_items = after.get(category, {})
            added = sorted(set(new_items) - set(old_items))
            removed = sorted(set(old_items) - set(new_items))
            updated = []
            for name in sorted(set(old_items) & set(new_items)):
                old, new = old_items[name], new_items[name]
                if self._richness(new) > self._richness(old):
                    updated.append(name)
            report[category] = {"added": added, "removed": removed, "updated": updated,
                                "local_count": len(old_items), "remote_count": len(new_items)}
        return report

    def run_sync_once(self) -> dict[str, Any]:
        """同步执行一轮：快照 → 全量拉取清洗入库 → 差异核对 → 写审计。

        必须在 to_thread 中调用（内部为阻塞网络请求）。返回核对报告 dict。
        """
        before = self._snapshot()
        categories = list(fetch_wiki.CATEGORIES.keys())
        fetch_wiki.run(categories, self._workers)  # 失败类别保留旧文件
        after = self._snapshot()
        report = {
            "ran_at": datetime.now().isoformat(timespec="seconds"),
            "diff": self.diff_report(before, after),
        }
        # 把核对差异并入 fetch_wiki 的审计文件（若本次 fetch 完全失败则保留原审计）。
        audit_path = self._data_dir / self._audit_name
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            if isinstance(audit, dict):
                audit["diff_check"] = report
                tmp = audit_path.with_name(audit_path.name + ".tmp")
                tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                tmp.replace(audit_path)
        except (json.JSONDecodeError, OSError):
            pass
        self.last_report = report
        return report

    @staticmethod
    def format_report(report: dict[str, Any]) -> str:
        """固定模板渲染核对报告（管理员回复/日志用，不透传上游细节）。"""
        lines = [f"Wiki 数据核对完成（{report.get('ran_at', '')}）"]
        for category, item in report.get("diff", {}).items():
            lines.append(
                f"{category}：本地 {item['local_count']} → 最新 {item['remote_count']}"
                f"（新增 {len(item['added'])}，移除 {len(item['removed'])}，内容更新 {len(item['updated'])}）")
            for name in item["added"][:8]:
                lines.append(f"  + {name}")
            for name in item["updated"][:8]:
                lines.append(f"  ~ {name}")
        return "\n".join(lines)

    # ---------- 调度 ----------

    def _seconds_until_next(self, now: datetime | None = None) -> float:
        now = now or datetime.now()
        target = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    async def schedule_loop(self) -> None:
        """每日 HH:MM 执行一轮核对；结果写日志与审计文件。

        to_thread 包裹阻塞爬取；CancelledError 直接退出（terminate 取消安全）。
        """
        while True:
            wait_seconds = self._seconds_until_next()
            LOGGER.info("wiki 数据核对计划在 %02d:%02d 执行（%.1f 小时后）",
                        self.hour, self.minute, wait_seconds / 3600)
            await asyncio.sleep(wait_seconds)
            try:
                report = await asyncio.to_thread(self.run_sync_once)
                LOGGER.info("%s", self.format_report(report).replace("\n", " | "))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 网络不可用/目录失败：保留本地数据，次日再试
                LOGGER.warning("wiki 数据核对失败（保留本地数据）：%s: %s", type(exc).__name__, exc)
                await asyncio.sleep(60)


def build_report_snapshot(data_dir: Path) -> dict[str, Any]:
    """只读工具：返回当前本地数据的粗略概览（条目数），供命令回显。"""
    data_dir = Path(data_dir)
    overview: dict[str, Any] = {}
    for category, (___, filename, __) in fetch_wiki.CATEGORIES.items():
        path = data_dir / filename
        count = 0
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                count = len(loaded) if isinstance(loaded, list) else 0
            except (json.JSONDecodeError, OSError):
                count = 0
        overview[category] = count
    return overview
