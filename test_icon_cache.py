"""W2/W8 · IconCache 图标缓存测试（全离线，httpx.MockTransport + tmp 目录）。

覆盖：本地命中直接返回路径、路径穿越（``..``）防护、单源重试耗尽返回 ""、
失败 2 次后成功落盘（.tmp + os.replace 原子写）、404 不重试、resolve_many 并发
解析、W8 多源回退（首源失败换下一源）、sticky 成功源、失败负缓存（TTL 内不再
打网络）、非 PNG 响应拒写盘。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_icon_cache.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters.icon_cache import IconCache

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-icon-bytes"
NOT_PNG = b"<html>blocked</html>"


def _cache(root: Path, handler, **kwargs) -> IconCache:
    kwargs.setdefault("backoff_base", 0.01)  # 测试里退避近零，不拖慢用例
    return IconCache(root=root, transport=httpx.MockTransport(handler), **kwargs)


def test_local_hit_returns_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "icon" / "character" / "1310.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(FAKE_PNG)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("本地命中不应发起网络请求")

    cache = _cache(tmp_path, handler)
    got = asyncio.run(cache.resolve("icon/character/1310.png"))
    assert got == str(target.resolve())
    assert asyncio.run(cache.resolve("icon/character/1310.png")) == got


def test_invalid_paths_return_empty(tmp_path: Path) -> None:
    cache = _cache(tmp_path, lambda request: pytest.fail("非法路径不应发起请求"))
    assert asyncio.run(cache.resolve("")) == ""
    assert asyncio.run(cache.resolve("icon/../secret.png")) == ""
    assert asyncio.run(cache.resolve("../escape.png")) == ""
    assert asyncio.run(cache.resolve("..\\escape.png")) == ""
    assert not (tmp_path / "secret.png").exists()


def test_retry_exhausted_returns_empty(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("boom")

    cache = _cache(tmp_path, handler, retries=3,
                   base_urls=("https://src.test/x",))  # 单源：尝试次数可精确断言
    assert asyncio.run(cache.resolve("icon/character/200.png")) == ""
    assert attempts["n"] == 4  # 首次 + 3 次重试（1s/2s/4s 退避，测试中缩放为 0.01 基数）
    assert not (tmp_path / "icon" / "character" / "200.png").exists()


def test_flaky_download_succeeds_atomically(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise httpx.ConnectError("flaky")
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler, retries=3,
                   base_urls=("https://src.test/x",))
    target = tmp_path / "icon" / "character" / "1310.png"
    got = asyncio.run(cache.resolve("icon/character/1310.png"))
    assert got == str(target.resolve())
    assert target.is_file() and target.read_bytes() == FAKE_PNG
    assert attempts["n"] == 3
    # 第二次解析走本地，不再发请求
    assert asyncio.run(cache.resolve("icon/character/1310.png")) == got
    assert attempts["n"] == 3


def test_404_not_retried(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404, text="nope")

    cache = _cache(tmp_path, handler)
    assert asyncio.run(cache.resolve("icon/character/404.png")) == ""
    assert attempts["n"] == 1  # 资源不存在，重试无意义


def test_http_error_status_not_written(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    cache = _cache(tmp_path, handler, retries=1,
                   base_urls=("https://src.test/x",))
    assert asyncio.run(cache.resolve("icon/relic/1.png")) == ""
    assert not (tmp_path / "icon" / "relic" / "1.png").exists()


def test_resolve_many(tmp_path: Path) -> None:
    existing = tmp_path / "icon" / "character" / "1310.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(FAKE_PNG)
    downloads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        downloads["n"] += 1
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler)
    result = asyncio.run(cache.resolve_many([
        "icon/character/1310.png",      # 本地命中
        "icon/character/1505.png",      # 下载
        "icon/character/1505.png",      # 重复，应去重
        "",                             # 空路径 → ""
        "icon/../evil.png",             # 非法 → ""
    ]))
    assert result["icon/character/1310.png"] == str(existing.resolve())
    assert result["icon/character/1505.png"] == str(
        (tmp_path / "icon" / "character" / "1505.png").resolve())
    assert (tmp_path / "icon" / "character" / "1505.png").is_file()
    assert result[""] == "" and result["icon/../evil.png"] == ""
    assert downloads["n"] == 1  # 去重后只下载一次


# ---------- W8 多源回退 / sticky / 负缓存 ----------


def test_multi_source_falls_back_to_next(tmp_path: Path) -> None:
    """首源持续失败 → 换下一源成功落盘；请求确实打到过两个源。"""
    hosts = {"first": 0, "second": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.test":
            hosts["first"] += 1
            raise httpx.ConnectError("unreachable")
        hosts["second"] += 1
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler, retries=1,
                   base_urls=("https://first.test/r", "https://second.test/r"))
    target = tmp_path / "icon" / "character" / "1310.png"
    got = asyncio.run(cache.resolve("icon/character/1310.png"))
    assert got == str(target.resolve()) and target.is_file()
    assert hosts["first"] == 2 and hosts["second"] == 1  # 每源各试 retries+1 次后换源


def test_sticky_source_prefers_last_success(tmp_path: Path) -> None:
    """成功源记忆（sticky）：后续下载直接从成功源开始，不再先撞坏源。"""
    hosts = {"bad": 0, "good": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bad.test":
            hosts["bad"] += 1
            raise httpx.ConnectError("down")
        hosts["good"] += 1
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler, retries=0,
                   base_urls=("https://bad.test/r", "https://good.test/r"))
    asyncio.run(cache.resolve("icon/a.png"))
    assert hosts == {"bad": 1, "good": 1}
    asyncio.run(cache.resolve("icon/b.png"))
    assert hosts == {"bad": 1, "good": 2}  # sticky：坏源不再被尝试


def test_negative_cache_skips_network_within_ttl(tmp_path: Path) -> None:
    """失败负缓存：同一坏路径 TTL 内不再发起网络尝试；本地文件不受负缓存影响。"""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("down")

    cache = _cache(tmp_path, handler, retries=0, base_urls=("https://src.test/r",))
    assert asyncio.run(cache.resolve("icon/x.png")) == ""
    assert attempts["n"] == 1
    assert asyncio.run(cache.resolve("icon/x.png")) == ""
    assert attempts["n"] == 1  # 负缓存生效，未再打网络
    # 本地补上文件后立即命中，与负缓存无关
    local = tmp_path / "icon" / "x.png"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(FAKE_PNG)
    assert asyncio.run(cache.resolve("icon/x.png")) == str(local.resolve())


def test_non_png_response_rejected_and_next_source_used(tmp_path: Path) -> None:
    """200 但内容非 PNG（错误页/反爬页）→ 不落盘，换源取真图。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fake.test":
            return httpx.Response(200, content=NOT_PNG)
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler, retries=0,
                   base_urls=("https://fake.test/r", "https://real.test/r"))
    target = tmp_path / "icon" / "y.png"
    got = asyncio.run(cache.resolve("icon/y.png"))
    assert got == str(target.resolve())
    assert target.read_bytes() == FAKE_PNG


def test_legacy_single_base_url_still_works(tmp_path: Path) -> None:
    """旧签名 base_url=... 保持单源模式（兼容 v0.4 调用方/脚本）。"""
    attempts = {"hosts": set()}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["hosts"].add(request.url.host)
        return httpx.Response(200, content=FAKE_PNG)

    cache = _cache(tmp_path, handler, base_url="https://legacy.test/r")
    assert asyncio.run(cache.resolve("icon/z.png")) != ""
    assert attempts["hosts"] == {"legacy.test"}
