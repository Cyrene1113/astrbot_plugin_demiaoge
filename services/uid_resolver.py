"""UID/别名解析与绑定参数校验（纯逻辑，无 IO 依赖 astrbot，可离线测）。

解析优先级（W7 防串号配套）：显式 UID 参数 > 本人 current 指针别名 > 本人 "default" 绑定。
store 需实现 ``get_bundle(owner_id, alias)``（CredentialStore 已满足，
dict keys: cookie/stoken/uid/bind_type/mid）与 ``get_current(owner_id)``。

防串号核心：本函数只解析**本人**的绑定（owner_id 固定为事件发送者）；显式 UID 参数
走公开数据路径（面板类查询），凭据类查询（体力等）永远不从这里拿他人凭据。
"""

from __future__ import annotations

import re
from typing import Any

# 显式 UID：6-11 位纯数字（比 §2 绑定命令的 9-10 位更宽，兼容历史/测试 UID）。
UID_PATTERN = re.compile(r"^\d{6,11}$")
DEFAULT_ALIAS = "default"

# 固定文案：绑定不存在 / 别名不合法 / UID 格式不正确（绝不拼接用户输入之外的动态内容）。
NO_BINDING_MESSAGE = "未找到该绑定，请先 /hsr 绑定 <UID> 或 /hsr 扫码。"
ALIAS_MESSAGE = "别名不合法：需为 1-16 个字符且不含空格。"
UID_MESSAGE = "UID 格式不正确：应为 6-11 位纯数字。"


def is_valid_uid(arg: Any) -> bool:
    """6-11 位纯数字视为合法 UID。"""
    return bool(UID_PATTERN.match(str(arg or "").strip()))


def is_valid_alias(alias: Any) -> bool:
    """别名合法性：非空、≤16 字、不含空白字符。"""
    text = str(alias or "")
    if not text or len(text) > 16:
        return False
    return not any(char.isspace() for char in text)


def resolve_uid(arg: Any, store: Any, owner_id: str) -> tuple[str | None, str]:
    """把命令参数解析为 UID（只解析本人绑定）。

    返回 ``(uid, "")`` 或 ``(None, 固定错误文案)``：

    - arg 为 6-11 位纯数字 → 直接作为 UID（公开数据查询）；
    - arg 为本人已有绑定别名 → 取该绑定存的 uid（老 Cookie 绑定无 uid 视为未绑定）；
    - arg 为 None/空 → 本人 current 指针别名（`/hsr 切换` 设置）→ "default" 别名；
    - 其余情况 → (None, NO_BINDING_MESSAGE)。
    """
    text = str(arg).strip() if arg is not None else ""
    if text:
        if UID_PATTERN.match(text):
            return text, ""
        bundle = _bundle_for(store, owner_id, text)
        if bundle and bundle.get("uid"):
            return str(bundle["uid"]), ""
        return None, NO_BINDING_MESSAGE
    for alias in _default_aliases(store, owner_id):
        bundle = _bundle_for(store, owner_id, alias)
        if bundle and bundle.get("uid"):
            return str(bundle["uid"]), ""
    return None, NO_BINDING_MESSAGE


def _default_aliases(store: Any, owner_id: str) -> tuple[str, ...]:
    """缺省别名候选：current 指针在前，"default" 兜底（去重保持顺序）。"""
    candidates = ["default"]
    if store is not None:
        try:
            current = str(store.get_current(owner_id) or "").strip()
        except Exception:
            current = ""
        if current:
            candidates.insert(0, current)
    return tuple(dict.fromkeys(candidates))


def _bundle_for(store: Any, owner_id: str, alias: str) -> dict[str, Any] | None:
    if store is None:
        return None
    try:
        return store.get_bundle(owner_id, alias)
    except Exception:
        # 凭据文件损坏/完整性校验失败等：按未绑定处理（主流程不因此中断出图路径）。
        return None
