"""W2 · CredentialStore v2 扩展测试（全离线，tmp 目录）。

覆盖：bind 新参数 roundtrip、get_bundle 解密、stoken 加密落盘（文件无明文）、
v0.3 老格式（仅 cookie/uid）向下兼容、list_accounts 不回显敏感字段。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_credentials_v2.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrbot_plugin_demiaoge.storage.credentials import CredentialStore

MASTER_KEY = "unit-test-master-key"
COOKIE = "ltoken=v2_ab; cookie_token=v2_cd; ltuid=100000001"
STOKEN = "v2_stoken_secret_value"


def _store(tmp_path: Path, name: str = "credentials.json") -> CredentialStore:
    return CredentialStore(tmp_path / name, master_key=MASTER_KEY)


def test_bind_v2_roundtrip_and_get_bundle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.bind("owner1", "default", COOKIE, uid="100000001",
               bind_type="qr", stoken=STOKEN, mid="mid-abc")
    bundle = store.get_bundle("owner1", "default")
    assert bundle == {
        "cookie": COOKIE,
        "stoken": STOKEN,
        "uid": "100000001",
        "bind_type": "qr",
        "mid": "mid-abc",
    }
    # get_cookie / list_accounts 老接口不受影响
    assert store.get_cookie("owner1", "default") == COOKIE
    assert store.list_accounts("owner1") == [
        {"alias": "default", "uid": "100000001", "cookie": "已设置"}
    ]


def test_stoken_and_cookie_never_plaintext_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = CredentialStore(path, master_key=MASTER_KEY)
    store.bind("owner1", "default", COOKIE, uid="100000001",
               bind_type="qr", stoken=STOKEN, mid="mid-abc")
    raw = path.read_text(encoding="utf-8")
    assert STOKEN not in raw, "stoken 明文泄漏到磁盘"
    assert "ltoken=v2_ab" not in raw, "cookie 明文泄漏到磁盘"
    assert STOKEN[:8] not in raw
    # 非敏感字段允许明文
    assert '"bind_type": "qr"' in raw
    assert "mid-abc" in raw
    # stoken 密文存在且与 cookie 密文不同（各自独立加密）
    record = json.loads(raw)["owner1"]["default"]
    assert record["stoken"] and record["stoken"] != record["cookie"]


def test_v03_old_format_compat(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = CredentialStore(path, master_key=MASTER_KEY)
    store.bind("owner2", "default", "cookie-old-value", uid="12345")
    # 手工把记录降级回 v0.3 结构（仅 cookie/uid 两个键）
    data = json.loads(path.read_text(encoding="utf-8"))
    data["owner2"]["default"] = {
        "cookie": data["owner2"]["default"]["cookie"],
        "uid": "12345",
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bundle = store.get_bundle("owner2", "default")
    assert bundle is not None
    assert bundle["cookie"] == "cookie-old-value"
    assert bundle["stoken"] == ""
    assert bundle["uid"] == "12345"
    assert bundle["bind_type"] == "uid"  # 缺失补默认
    assert bundle["mid"] == ""
    assert store.get_cookie("owner2", "default") == "cookie-old-value"


def test_v02_style_uid_only_cookie_missing(tmp_path: Path) -> None:
    """极端老数据：连 cookie 键都没有也不报错。"""
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"owner3": {"default": {"uid": "9"}}}, ensure_ascii=False),
                    encoding="utf-8")
    store = CredentialStore(path, master_key=MASTER_KEY)
    bundle = store.get_bundle("owner3", "default")
    assert bundle == {"cookie": "", "stoken": "", "uid": "9", "bind_type": "uid", "mid": ""}
    assert store.get_cookie("owner3", "default") is None


def test_get_bundle_missing_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_bundle("nobody", "default") is None


def test_list_accounts_never_adds_sensitive_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.bind("owner4", "default", COOKIE, uid="1", bind_type="qr", stoken=STOKEN, mid="m")
    listing = store.list_accounts("owner4")
    assert all(set(item) == {"alias", "uid", "cookie"} for item in listing)
    assert all("stoken" not in json.dumps(item) for item in listing)


def test_bind_validation_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.bind("owner5", "default", "   ")
    with pytest.raises(ValueError):
        store.bind("", "default", COOKIE)


# ---------- W8 · 凭据文件损坏容错 ----------


def test_corrupt_file_backed_up_and_reset(tmp_path: Path) -> None:
    """文件损坏（半写/磁盘故障）→ 备份现场 + 按空库处理，功能保命不 500。"""
    path = tmp_path / "credentials.json"
    path.write_text('{"owner1": {"default": {"cooki', encoding="utf-8")  # 半截 JSON
    store = CredentialStore(path, master_key=MASTER_KEY)
    assert store.list_accounts("owner1") == []  # 空库，不抛
    assert store.get_bundle("owner1", "default") is None
    # 现场备份为 .corrupt-<时间戳>，不静默丢弃
    backups = list(tmp_path.glob("credentials.json.corrupt-*"))
    assert len(backups) == 1 and "cooki" in backups[0].read_text(encoding="utf-8")
    # 重置后可正常写入新绑定
    store.bind("owner2", "default", COOKIE, uid="100000001")
    assert store.get_bundle("owner2", "default")["uid"] == "100000001"


def test_corrupt_file_recovery_via_bind(tmp_path: Path) -> None:
    """损坏后下一次 bind 直接重建合法文件（原子写覆盖空库）。"""
    path = tmp_path / "credentials.json"
    path.write_text("not-json{{{", encoding="utf-8")
    store = CredentialStore(path, master_key=MASTER_KEY)
    store.bind("owner9", "default", COOKIE, uid="42")
    fresh = CredentialStore(path, master_key=MASTER_KEY)
    assert fresh.get_bundle("owner9", "default")["uid"] == "42"
    assert not list(tmp_path.glob("*.tmp"))  # 无残留临时文件
