"""StarRailRes 图标缓存：相对路径 → 本地文件（api_notes §1.4）。

- 多源回退（W8）：``raw.githubusercontent.com`` 在部分网络环境不可达（W1-A/W8 实测
  读超时），故默认源列表为 jsDelivr 三镜像优先、raw 兜底；同一路径逐源尝试，
  成功源记忆为首选（sticky），后续下载不再在坏源上浪费超时。
- ``resolve(rel_path)``：本地命中直接返回绝对路径；未命中异步下载，先写 ``.tmp``
  再 ``os.replace`` 原子落盘；全部失败返回 ``""``（渲染层已有占位逻辑）。
- 失败负缓存（内存，10 分钟 TTL）：下载失败的路径在 TTL 内不再发起网络尝试，
  避免上游 404/断网时每条命令重复打网络；本地文件命中不受负缓存影响。
- 路径穿越防护：rel_path 为空或含 ``..`` 直接返回 ``""``。
- 并发限制：信号量 6（``resolve_many`` 用 asyncio.gather 复用）。
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx

BASE_URL = "https://raw.githubusercontent.com/Mar-7th/StarRailRes/master"
# 默认源顺序：jsDelivr 三镜像（实测可达且快）在前，GitHub raw 兜底。
DEFAULT_BASE_URLS = (
    "https://cdn.jsdelivr.net/gh/Mar-7th/StarRailRes@master",
    "https://gcore.jsdelivr.net/gh/Mar-7th/StarRailRes@master",
    "https://testingcf.jsdelivr.net/gh/Mar-7th/StarRailRes@master",
    BASE_URL,
)
NEGATIVE_TTL_SECONDS = 600.0  # 下载失败负缓存：10 分钟内同路径不再尝试网络
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "icons"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Demiaoge/0.4"
)


class IconCache:
    """图标磁盘缓存（相对路径结构保留在 ``root`` 下）。"""

    def __init__(self, base_url: str = "", root: Path | None = None,
                 timeout: float = 10.0, retries: int = 3, backoff_base: float = 1.0,
                 transport: httpx.AsyncBaseTransport | None = None,
                 base_urls: tuple[str, ...] | None = None) -> None:
        # 兼容旧签名：显式传 base_url → 单源模式；否则 base_urls 或默认多源。
        if base_url:
            sources: tuple[str, ...] = (base_url,)
        elif base_urls:
            sources = tuple(base_urls)
        else:
            sources = DEFAULT_BASE_URLS
        self._sources = tuple(url.rstrip("/") for url in sources if url and url.strip())
        if not self._sources:
            self._sources = DEFAULT_BASE_URLS
        self.root = Path(root) if root else DEFAULT_ROOT
        self._timeout = timeout
        self._retries = retries
        self._backoff_base = backoff_base
        self._transport = transport
        self._semaphore = asyncio.Semaphore(6)
        self._memory: dict[str, str] = {}
        self._preferred = 0  # sticky 成功源索引：优先复用上次成功的源
        self._negative: dict[str, float] = {}  # rel_path → 失败时刻（monotonic）
        self._client: httpx.AsyncClient | None = None  # 共享连接池（TLS 复用，W8）
        self._client_loop_id: int | None = None

    def local_path(self, rel_path: str) -> Path | None:
        """本地已有该图标时返回其路径，否则 None（路径非法一律 None）。"""
        local = self._safe_local(rel_path)
        if local is not None and local.is_file():
            return local
        return None

    def _safe_local(self, rel_path: str) -> Path | None:
        rel = (rel_path or "").strip().lstrip("/")
        if not rel or ".." in rel:
            return None
        return self.root / rel

    async def resolve(self, rel_path: str) -> str:
        """相对路径 → 本地绝对路径；下载失败 / 非法路径返回 ""。"""
        rel = (rel_path or "").strip().lstrip("/")
        if not rel or ".." in rel:
            return ""
        cached = self._memory.get(rel)
        if cached:
            return cached
        local = self.root / rel
        if local.is_file():
            resolved = str(local.resolve())
            self._memory[rel] = resolved
            self._negative.pop(rel, None)
            return resolved
        failed_at = self._negative.get(rel)
        if failed_at is not None and time.monotonic() - failed_at < NEGATIVE_TTL_SECONDS:
            return ""  # 负缓存：近期失败过的路径不再打网络（本地已查过、未命中）
        async with self._semaphore:
            # 双检：并发 gather 时同一图标只下载一次。
            if local.is_file():
                resolved = str(local.resolve())
                self._memory[rel] = resolved
                return resolved
            if await self._download(rel, local):
                resolved = str(local.resolve())
                self._memory[rel] = resolved
                return resolved
        return ""

    async def resolve_many(self, paths) -> dict[str, str]:
        """并发解析一批相对路径（信号量 6），返回 {rel_path: 本地路径或 ""}。

        空 / 含 ``..`` 等非法路径也会出现在结果里，值为 ``""``（resolve 统一防护）。
        """
        unique = list(dict.fromkeys(paths))
        pairs = await asyncio.gather(*(self._resolve_pair(p) for p in unique))
        return dict(pairs)

    async def _resolve_pair(self, rel_path: str) -> tuple[str, str]:
        return rel_path, await self.resolve(rel_path)

    def _get_client(self) -> httpx.AsyncClient:
        """共享 AsyncClient（连接/TLS 复用）；事件循环变化（测试多次 asyncio.run）时重建。"""
        loop_id = id(asyncio.get_running_loop())
        if self._client is None or self._client_loop_id != loop_id:
            # 旧 client 绑定已关闭的循环，无法跨循环 await 关闭，直接丢弃由 GC 回收
            self._client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport,
                                             headers={"User-Agent": USER_AGENT},
                                             follow_redirects=True)
            self._client_loop_id = loop_id
        return self._client

    async def aclose(self) -> None:
        """关闭共享连接池（main.terminate 收尾用；非必须调用）。"""
        client, self._client = self._client, None
        self._client_loop_id = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass  # 收尾路径，关闭失败不阻塞退出

    async def _download(self, rel: str, local: Path) -> bool:
        """跨源下载（sticky 首选源在前）；成功后 .tmp + os.replace 原子落盘。

        每源各尝试 ``retries + 1`` 次（退避 1s/2s/4s…）；HTTP 404 表示资源在
        StarRailRes 仓库中不存在（各镜像同构），不再换源/重试，直接记负缓存。
        """
        url_suffix = f"/{rel}"
        order = [self._preferred] + [i for i in range(len(self._sources)) if i != self._preferred]
        client = self._get_client()
        for source_index in order:
            url = self._sources[source_index] + url_suffix
            for attempt in range(self._retries + 1):
                try:
                    response = await client.get(url)
                    if response.status_code == 200 and response.content:
                        if response.content[:8] != b"\x89PNG\r\n\x1a\n":
                            # 非 PNG（如错误页/HTML）：当下载失败处理，退避后重试/换源。
                            pass
                        else:
                            self._atomic_write(local, response.content)
                            self._preferred = source_index
                            self._negative.pop(rel, None)
                            return True
                    if response.status_code == 404:
                        self._negative[rel] = time.monotonic()
                        return False  # 资源确实不存在，重试无意义
                except (httpx.HTTPError, OSError):
                    pass  # 网络抖动（api_notes 实测 10054/握手超时），退避后重试
                if attempt < self._retries:
                    await asyncio.sleep(self._backoff_base * (2 ** attempt))
        self._negative[rel] = time.monotonic()
        return False

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        tmp = target.parent / (target.name + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(content)
            os.replace(tmp, target)
        except OSError:
            # 落盘失败按下载失败处理（返回 ""），绝不阻塞主流程。
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
