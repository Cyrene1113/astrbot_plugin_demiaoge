"""Wiki 在线数据源适配器骨架。

在线更新应由后台任务调用，查询服务只读取本地缓存，避免阻塞用户请求。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WikiFetchResult:
    records: tuple[dict[str, Any], ...]
    version: str = ""


class WikiSource:
    """Wiki 数据源适配器接口。"""

    async def fetch(self) -> WikiFetchResult:
        raise NotImplementedError


class BiligameWikiSource(WikiSource):
    """B 站星铁 Wiki（biligame）公开源适配器骨架。"""

    def __init__(self, endpoint: str = "", user_agent: str = "DemiaogeWiki/0.1") -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent

    async def fetch(self) -> WikiFetchResult:
        # TODO: 根据 biligame 公开接口响应实现解析；不要在查询协程中直接调用。
        await asyncio.sleep(0)
        return WikiFetchResult(())


class MihoyoWikiSource(WikiSource):
    """米游社备用 Wiki 源适配器骨架。"""

    def __init__(self, endpoint: str = "", user_agent: str = "DemiaogeWiki/0.1") -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent

    async def fetch(self) -> WikiFetchResult:
        # TODO: 接入公开接口，按限速策略请求并映射为 WikiEntry 记录。
        await asyncio.sleep(0)
        return WikiFetchResult(())
