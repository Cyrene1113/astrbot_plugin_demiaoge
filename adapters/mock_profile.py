"""角色数据 Port 的 mock 实现；后续替换为米游社 Adapter + Mapper。"""

from __future__ import annotations

from ..domain.models import CharacterSummary, PlayerProfile


class ProfileAdapter:
    async def get_profile(self, uid: str, cookie: str, request_id: str) -> PlayerProfile:
        """返回脱敏领域对象，不向上层暴露厂商 JSON。"""
        return PlayerProfile(
            uid=uid or "mock-uid",
            nickname="开拓者（Mock）",
            level=70,
            characters=(
                CharacterSummary("开拓者", 80, 6),
                CharacterSummary("黄泉", 80, 2),
                CharacterSummary("知更鸟", 80, 1),
            ),
        )
