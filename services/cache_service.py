"""面板 JSON 的 TTL 缓存（内存 + 磁盘双层）。

- 磁盘：``data/profile_cache/{uid}.json``，内容 = 面板原始 parsed JSON + ``fetched_at``。
- 命中顺序：内存（未过期）→ 磁盘（校验 ``fetched_at`` TTL）→ 未命中。
- 过期/损坏 → 返回 ``None`` 并删除坏文件；写入一律 ``.tmp`` + ``os.replace`` 原子落盘。
- 单进程使用（AstrBot 单实例事件循环内），不加锁。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

DEFAULT_DISK_DIR = Path(__file__).resolve().parents[1] / "data" / "profile_cache"
_SAFE_NAME = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
FETCHED_AT_KEY = "fetched_at"

# 成图缓存默认保留天数：内容哈希键下旧图永不复用，定期回收防目录无限膨胀
# （数据每变一次就多一张 PNG；管理员仍可 /hsr 更新缓存 立即全清）。
CARD_CACHE_MAX_AGE_DAYS = 7.0
CARD_CACHE_CLEAN_INTERVAL_SECONDS = 24 * 3600.0


class ProfileCache:
    """按 UID 缓存 Mihomo parsed 面板 JSON。"""

    def __init__(self, disk_dir: Path | None = None, ttl_seconds: int = 600) -> None:
        self.disk_dir = Path(disk_dir) if disk_dir else DEFAULT_DISK_DIR
        self.disk_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = int(ttl_seconds)
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}

    def _file_for(self, uid: str) -> Path | None:
        name = str(uid)
        if not _SAFE_NAME.match(name):
            # 非常规 UID（理论不该出现）哈希成安全文件名，防路径注入。
            name = hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
        return self.disk_dir / f"{name}.json"

    def get(self, uid: str) -> dict[str, Any] | None:
        """命中返回含 fetched_at 的 payload dict；过期/损坏返回 None 并清文件。"""
        now = time.time()
        entry = self._memory.get(str(uid))
        if entry is not None:
            stored_at, payload = entry
            if now - stored_at <= self.ttl_seconds:
                return payload
            self._memory.pop(str(uid), None)

        path = self._file_for(uid)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(data[FETCHED_AT_KEY])
        except (OSError, ValueError, KeyError, TypeError):
            self._remove(path)  # 损坏文件：删除并视为未命中
            return None
        if now - fetched_at > self.ttl_seconds:
            self._remove(path)  # 过期文件一并清理，下次查询重新拉取
            return None
        if not isinstance(data, dict):
            self._remove(path)
            return None
        self._memory[str(uid)] = (fetched_at, data)
        return data

    def put(self, uid: str, payload: dict[str, Any]) -> None:
        """写入内存 + 磁盘（payload 顶层附 fetched_at）。"""
        now = time.time()
        data = dict(payload)
        data[FETCHED_AT_KEY] = now
        self._memory[str(uid)] = (now, data)
        path = self._file_for(uid)
        if path is None:
            return
        tmp = path.parent / (path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass  # 磁盘写失败不影响内存命中

    def invalidate(self, uid: str | None = None) -> None:
        """清空指定 UID（或全部）的内存与磁盘缓存。"""
        if uid is None:
            self._memory.clear()
            for path in self.disk_dir.glob("*.json"):
                self._remove(path)
            return
        self._memory.pop(str(uid), None)
        path = self._file_for(uid)
        if path is not None:
            self._remove(path)

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def clean_card_cache(card_dir: Path, max_age_days: float = CARD_CACHE_MAX_AGE_DAYS) -> int:
    """删除成图缓存目录中超期未更新的 PNG（同步函数，事件循环上请 to_thread 调用）。

    内容哈希缓存键下旧图永不复用（数据一变键即变），按 mtime 回收超期文件即可，
    不需要 LRU 精细化。二维码（qr_*.png）同目录且会话仅 180s，一并回收。
    返回删除的文件数；目录不存在返回 0。单文件失败跳过，不中断整轮清理。
    """
    directory = Path(card_dir)
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for path in directory.glob("*.png"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue  # 文件被占用/权限问题：跳过，下轮再试
    return removed
