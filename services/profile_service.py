"""角色查询用例。"""

from __future__ import annotations

from typing import Protocol

from ..domain.models import PlayerProfile
from ..storage.credentials import CredentialStore


class ProfileAdapter(Protocol):
    async def get_profile(self, uid: str, cookie: str, request_id: str) -> PlayerProfile: ...


class ProfileService:
    def __init__(self, store: CredentialStore, adapter: ProfileAdapter) -> None:
        self.store = store
        self.adapter = adapter

    async def get_profile(self, owner_id: str, alias: str, request_id: str) -> PlayerProfile | None:
        account = next((x for x in self.store.list_accounts(owner_id) if x["alias"] == alias), None)
        if not account:
            return None
        cookie = self.store.get_cookie(owner_id, alias)
        return await self.adapter.get_profile(account["uid"], cookie or "", request_id)

    @staticmethod
    def format_profile(profile: PlayerProfile, request_id: str) -> str:
        lines = [f"星穹铁道角色（request_id: {request_id}）", f"UID：{profile.uid} | 开拓等级：{profile.level}"]
        lines.extend(f"- {c.name}：Lv.{c.level}，命座/E：{c.eidolons}" for c in profile.characters)
        return "\n".join(lines)

    async def query(self, owner_id: str, alias: str, request_id: str) -> str:
        profile = await self.get_profile(owner_id, alias, request_id)
        if profile is None:
            return "尚未绑定账号，请先使用 /hsr bind <Cookie>。"
        return self.format_profile(profile, request_id)
