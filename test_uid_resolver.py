"""W3 · UID/别名解析测试（全离线，真实 CredentialStore + 临时目录）。

覆盖 resolve_uid 四分支：显式 UID / 已绑定别名 / default 缺省 / 未绑定；
附 UID 与别名合法性校验。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_uid_resolver.py
"""
from __future__ import annotations

import pytest

from astrbot_plugin_demiaoge.services.uid_resolver import (
    ALIAS_MESSAGE,
    DEFAULT_ALIAS,
    NO_BINDING_MESSAGE,
    UID_MESSAGE,
    is_valid_alias,
    is_valid_uid,
    resolve_uid,
)
from astrbot_plugin_demiaoge.storage.credentials import CredentialStore

OWNER = "10001"


@pytest.fixture()
def store(tmp_path):
    return CredentialStore(tmp_path / "credentials.json", "unit-test-master-key")


def test_explicit_uid_digits_pass_through(store) -> None:
    assert resolve_uid("100895290", store, OWNER) == ("100895290", "")
    assert resolve_uid(" 100000001 ", store, OWNER) == ("100000001", "")  # 首尾空白容忍


def test_alias_resolves_to_bound_uid(store) -> None:
    store.bind(OWNER, "小号", "placeholder", uid="100000002", bind_type="uid")
    assert resolve_uid("小号", store, OWNER) == ("100000002", "")


def test_none_uses_default_binding(store) -> None:
    store.bind(OWNER, DEFAULT_ALIAS, "placeholder", uid="100000003", bind_type="uid")
    assert resolve_uid(None, store, OWNER) == ("100000003", "")
    assert resolve_uid("", store, OWNER) == ("100000003", "")


def test_unbound_returns_fixed_message(store) -> None:
    assert resolve_uid(None, store, OWNER) == (None, NO_BINDING_MESSAGE)
    assert resolve_uid("ghost", store, OWNER) == (None, NO_BINDING_MESSAGE)
    # 其他用户的 default 绑定不可见
    store.bind("someone-else", DEFAULT_ALIAS, "placeholder", uid="100000004")
    assert resolve_uid(None, store, OWNER) == (None, NO_BINDING_MESSAGE)


def test_no_store_behaves_as_unbound() -> None:
    assert resolve_uid(None, None, OWNER) == (None, NO_BINDING_MESSAGE)
    assert resolve_uid("alias", None, OWNER) == (None, NO_BINDING_MESSAGE)


def test_old_cookie_binding_without_uid_is_unbound(store) -> None:
    store.bind(OWNER, "legacy", "cookie-value")  # 未写 uid 的 v0.3 老绑定
    assert resolve_uid("legacy", store, OWNER) == (None, NO_BINDING_MESSAGE)


def test_non_uid_non_alias_digits_fall_to_alias_lookup(store) -> None:
    # 5 位 / 12 位不是合法 UID，也不是别名 → 未绑定文案
    assert resolve_uid("12345", store, OWNER) == (None, NO_BINDING_MESSAGE)
    assert resolve_uid("123456789012", store, OWNER) == (None, NO_BINDING_MESSAGE)


def test_is_valid_uid() -> None:
    assert is_valid_uid("100000001")
    assert not is_valid_uid("12345")
    assert not is_valid_uid("1234567890123")
    assert not is_valid_uid("abc123456")
    assert not is_valid_uid("")
    assert not is_valid_uid(None)


def test_is_valid_alias_rules() -> None:
    assert is_valid_alias("default")
    assert is_valid_alias("小号")
    assert is_valid_alias("a" * 16)
    assert not is_valid_alias("")
    assert not is_valid_alias("a b")  # 含空格
    assert not is_valid_alias("a\tb")
    assert not is_valid_alias("a" * 17)  # 超 16 字
    assert not is_valid_alias(None)


def test_alias_message_constant_is_fixed_text() -> None:
    # 固定文案回归锚：别名不合法提示不携带用户输入。
    assert ALIAS_MESSAGE == "别名不合法：需为 1-16 个字符且不含空格。"
    assert UID_MESSAGE == "UID 格式不正确：应为 6-11 位纯数字。"
