"""W2 · ProfileCache TTL 缓存测试（全离线，tmp 目录）。

覆盖：内存/磁盘命中、TTL 过期（monkeypatch time.time）、坏 JSON/缺 fetched_at
清理、invalidate 单个与全部、内存命中兜底（磁盘文件被删仍可读）。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_cache_service.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from astrbot_plugin_demiaoge.services.cache_service import ProfileCache

PAYLOAD = {"player": {"uid": "1001", "nickname": "测试"}, "characters": [{"id": "1310"}]}


def test_put_then_get_hit(tmp_path: Path) -> None:
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("1001", PAYLOAD)
    got = cache.get("1001")
    assert got is not None
    assert got["player"]["uid"] == "1001" and got["characters"] == PAYLOAD["characters"]
    assert got["fetched_at"] > 0  # 顶层附 fetched_at
    assert (tmp_path / "1001.json").is_file()


def test_disk_roundtrip_across_instances(tmp_path: Path) -> None:
    ProfileCache(disk_dir=tmp_path, ttl_seconds=600).put("1002", PAYLOAD)
    fresh = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)  # 新实例内存为空
    got = fresh.get("1002")
    assert got is not None and got["player"]["uid"] == "1001"


def test_memory_hit_even_if_disk_removed(tmp_path: Path) -> None:
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("1003", {"a": 1})
    (tmp_path / "1003.json").unlink()
    got = cache.get("1003")
    assert got is not None and got["a"] == 1


def test_ttl_expiry_monkeypatched_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("1004", PAYLOAD)
    assert cache.get("1004") is not None
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 601)  # 越过 TTL
    assert cache.get("1004") is None  # 内存与磁盘都过期
    assert not (tmp_path / "1004.json").exists()  # 过期文件被清


def test_disk_ttl_expiry_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """内存未过期但磁盘已过期（另一进程写的旧文件）→ 走磁盘 TTL 校验。"""
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("1005", PAYLOAD)
    real_time = time.time
    stale = {"player": {"uid": "1005"}, "fetched_at": real_time() - 3600}
    (tmp_path / "1005.json").write_text(json.dumps(stale), encoding="utf-8")
    # 内存里还是新鲜的 → 命中内存
    assert cache.get("1005")["fetched_at"] != stale["fetched_at"]
    # 换新实例（内存为空）→ 磁盘 fetched_at 过期 → None 且文件被清
    fresh = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    assert fresh.get("1005") is None
    assert not (tmp_path / "1005.json").exists()


def test_corrupt_json_removed(tmp_path: Path) -> None:
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("1006", PAYLOAD)
    (tmp_path / "1006.json").write_text("not-json{{{", encoding="utf-8")
    fresh = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    assert fresh.get("1006") is None
    assert not (tmp_path / "1006.json").exists()


def test_missing_fetched_at_removed(tmp_path: Path) -> None:
    (tmp_path / "1007.json").write_text(json.dumps({"player": {"uid": "1007"}}), encoding="utf-8")
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    assert cache.get("1007") is None
    assert not (tmp_path / "1007.json").exists()


def test_invalidate_single_and_all(tmp_path: Path) -> None:
    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("2001", {"v": 1})
    cache.put("2002", {"v": 2})
    cache.invalidate("2001")
    assert cache.get("2001") is None and not (tmp_path / "2001.json").exists()
    assert cache.get("2002") is not None
    cache.invalidate()
    assert cache.get("2002") is None and not (tmp_path / "2002.json").exists()


def test_unsafe_uid_never_escapes_disk_dir(tmp_path: Path) -> None:
    import hashlib

    cache = ProfileCache(disk_dir=tmp_path, ttl_seconds=600)
    cache.put("../../evil", {"v": 1})
    cache.put("ok", {"v": 2})
    # 非常规 UID 哈希成安全文件名，仍可读写，且不逃出磁盘目录
    hashed = hashlib.sha256("../../evil".encode("utf-8")).hexdigest()[:32]
    assert (tmp_path / f"{hashed}.json").is_file()
    got = cache.get("../../evil")
    assert got is not None and got["v"] == 1 and "fetched_at" in got
    names = {p.name for p in tmp_path.iterdir()}
    assert "evil.json" not in names and "ok.json" in names
    assert all(name.endswith((".json", ".tmp")) for name in names)


# ---------- W8 · clean_card_cache 成图缓存回收 ----------


def test_clean_card_cache_removes_only_expired(tmp_path: Path) -> None:
    from astrbot_plugin_demiaoge.services.cache_service import clean_card_cache

    fresh = tmp_path / "panel_a.png"
    stale = tmp_path / "panel_b.png"
    qr = tmp_path / "qr_ticket.png"
    other = tmp_path / "notes.txt"
    for path in (fresh, stale, qr, other):
        path.write_bytes(b"x")
    old = time.time() - 8 * 86400  # 超过默认 7 天
    import os
    os.utime(stale, (old, old))
    os.utime(qr, (old, old))

    removed = clean_card_cache(tmp_path)
    assert removed == 2
    assert fresh.is_file() and other.is_file()  # 新图与非 PNG 不动
    assert not stale.exists() and not qr.exists()  # 超期 PNG（含二维码）被清


def test_clean_card_cache_custom_age_and_missing_dir(tmp_path: Path) -> None:
    from astrbot_plugin_demiaoge.services.cache_service import clean_card_cache

    assert clean_card_cache(tmp_path / "nope") == 0  # 目录不存在 → 0，不抛
    png = tmp_path / "a.png"
    png.write_bytes(b"x")
    old = time.time() - 2 * 86400
    import os
    os.utime(png, (old, old))
    assert clean_card_cache(tmp_path, max_age_days=3) == 0  # 未到期不删
    assert png.is_file()
    assert clean_card_cache(tmp_path, max_age_days=1) == 1  # 到期删除
    assert not png.exists()
