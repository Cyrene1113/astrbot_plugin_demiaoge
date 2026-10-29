"""W2 · DS 签名与 game_record 降级客户端测试（全离线）。

- ds_simple / ds_bq：固定 t/r/salt 的预期 md5 为独立按公式预计算后写死（见各断言）；
  覆盖 b/q 两种形态（GET b 空 q 字母序、POST b=JSON q 空）与头格式 ``{t},{r},{sign}``。
- MihoyoRecordClient：MockTransport 模拟 retcode，校验请求头组合（DS 与实际 query
  逐字一致、app_version/client_type/Referer/UA）与 retcode → 固定文案错误映射。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_ds_sign.py
"""
from __future__ import annotations

import asyncio
import hashlib
import time

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters import ds as ds_mod
from astrbot_plugin_demiaoge.adapters.ds import SALT_PROD, SALT_X4, ds_bq, ds_simple
from astrbot_plugin_demiaoge.adapters.mihoyo_record import MihoyoRecordClient, resolve_server
from astrbot_plugin_demiaoge.domain.errors import (
    CookieExpiredError,
    DemiaogeError,
    ErrorCode,
    RateLimitedError,
)

T = 1700000000
R = "123456"


def test_ds_simple_fixed_values() -> None:
    # 独立预计算：md5("salt=xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs&t=1700000000&r=123456")
    assert ds_simple(SALT_X4, t=T, r=R) == "1700000000,123456,aded9fbbb30c62b34dbc0be62bef1161"
    # md5("salt=JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS&t=1700000000&r=123456")
    assert ds_simple(SALT_PROD, t=T, r=R) == "1700000000,123456,929d30b2a412a7494f1ab3b57153c3d4"


def test_ds_bq_get_form() -> None:
    query = "role_id=100895290&server=prod_gf_cn"
    # 独立预计算：md5(f"salt={X4}&t={T}&r={R}&b=&q={query}")
    expected = "1700000000,123456,b16b2fc88baf32ea656b255f4c2bc3c7"
    assert ds_bq(SALT_X4, body="", query=query, t=T, r=R) == expected


def test_ds_bq_post_forms() -> None:
    # 空对象 body 固定 "{}"，q 留空
    assert ds_bq(SALT_X4, body="{}", query="", t=T, r=R) == "1700000000,123456,6d46b7d413f5dee40f241fdc5053701a"
    # PROD salt + 真实 JSON body
    assert ds_bq(SALT_PROD, body='{"ticket":"tk-1"}', query="", t=T, r=R
                 ) == "1700000000,123456,57f3ab796d5bc19dbfc02cca66ce7c50"


def test_ds_header_format_and_defaults() -> None:
    before = int(time.time())
    header = ds_bq(SALT_X4, body="", query="role_id=1&server=prod_gf_cn")
    after = int(time.time())
    t_raw, r_raw, sign = header.split(",")
    assert t_raw.isdigit() and before <= int(t_raw) <= after
    assert len(r_raw) == 6 and r_raw.isdigit() and 100000 <= int(r_raw) <= 200000
    expected = hashlib.md5(
        f"salt={SALT_X4}&t={t_raw}&r={r_raw}&b=&q=role_id=1&server=prod_gf_cn".encode()
    ).hexdigest()
    assert sign == expected
    # salt 常量与 api_notes §3.2 一致
    assert ds_mod.SALT_X4 == "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
    assert ds_mod.SALT_PROD == "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"


def test_resolve_server() -> None:
    for uid in ("1", "2", "5"):
        assert resolve_server(uid) == "prod_gf_cn"
    for uid in ("6", "7"):
        assert resolve_server(uid) == "prod_qd_cn"


def _record_client(handler) -> MihoyoRecordClient:
    return MihoyoRecordClient(transport=httpx.MockTransport(handler))


def test_fetch_index_success_and_headers() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ds"] = request.headers.get("DS", "")
        captured["app_version"] = request.headers.get("x-rpc-app_version", "")
        captured["client_type"] = request.headers.get("x-rpc-client_type", "")
        captured["referer"] = request.headers.get("Referer", "")
        captured["ua"] = request.headers.get("User-Agent", "")
        captured["cookie"] = request.headers.get("Cookie", "")
        captured["query"] = request.url.query.decode()
        return httpx.Response(200, json={"retcode": 0, "message": "OK",
                                         "data": {"world_level": 6, "stats": []}})

    result = asyncio.run(_record_client(handler).fetch_index(
        "100895290", "prod_gf_cn", "ltoken=abc; ltuid=100895290", "rid-1"))
    assert result == {"world_level": 6, "stats": []}
    # query 与 DS 的 q 逐字一致（字母序 role_id < server），DS 签名可用请求内 t/r 复算验证
    assert captured["query"] == "role_id=100895290&server=prod_gf_cn"
    t_raw, r_raw, sign = captured["ds"].split(",")
    expected = hashlib.md5(
        f"salt={SALT_X4}&t={t_raw}&r={r_raw}&b=&q={captured['query']}".encode()
    ).hexdigest()
    assert sign == expected
    assert captured["app_version"] == "2.40.1"
    assert captured["client_type"] == "5"
    assert captured["referer"] == "https://webstatic.mihoyo.com/"
    assert captured["ua"].endswith("miHoYoBBS/2.40.1")
    assert captured["cookie"] == "ltoken=abc; ltuid=100895290"


@pytest.mark.parametrize("code,exc_type", [(-101, CookieExpiredError), (-110, RateLimitedError)])
def test_fetch_index_auth_errors(code: int, exc_type: type[Exception]) -> None:
    handler = lambda request: httpx.Response(200, json={"retcode": code, "message": "secret-upstream"})
    with pytest.raises(exc_type):
        asyncio.run(_record_client(handler).fetch_index("1", "prod_gf_cn", "cookie", "rid"))


def test_fetch_index_verify_and_other_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"retcode": 1034, "message": "verify-needed"})

    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_record_client(handler).fetch_index("1", "prod_gf_cn", "cookie", "rid"))
    assert exc.value.code == ErrorCode.AUTH_MISSING
    assert str(exc.value) == "触发了安全验证，请稍后再试。"

    other = lambda request: httpx.Response(200, json={"retcode": -999, "message": "whatever"})
    with pytest.raises(DemiaogeError) as exc2:
        asyncio.run(_record_client(other).fetch_index("1", "prod_gf_cn", "cookie", "rid"))
    assert exc2.value.code == ErrorCode.UPSTREAM_NETWORK
    assert str(exc2.value) == "米游社服务暂时不可用。"


def test_fetch_index_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_record_client(handler).fetch_index("1", "prod_gf_cn", "cookie", "rid"))
    assert exc.value.code == ErrorCode.UPSTREAM_NETWORK
    assert str(exc.value) == "米游社服务暂时不可用。"
