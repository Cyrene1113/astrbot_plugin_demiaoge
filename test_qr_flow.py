"""W2 · 扫码登录原语测试（全离线，httpx.MockTransport）。

覆盖：create（头组合 + retcode!=0 固定文案）→ query 状态序列
Created → Scanned → Confirmed（user_info + Set-Cookie 手动解析）→
-3501/-3505/-3503/未知 retcode 映射 → complete_with_stoken 补齐与静默失败。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_qr_flow.py
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters.mihoyo_auth import (
    CookieBundle,
    MihoyoQrAuth,
    QrPollResult,
)
from astrbot_plugin_demiaoge.domain.errors import DemiaogeError, ErrorCode

CREATE_URL = "https://passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin"
QUERY_URL = "https://passport-api.miyoushe.com/account/ma-cn-passport/web/queryQRLoginStatus"
FAKE_URL = "https://user.mihoyo.com/login-platform/mobile.html?expire=1&tk=tk-1&token_types=4#/login/qr"

CONFIRMED_COOKIES = [
    ("set-cookie", "cookie_token_v2=v2_ct_value; Path=/; Domain=.mihoyo.com; HttpOnly"),
    ("set-cookie", "ltoken_v2=v2_lt_value; Path=/; Domain=.mihoyo.com; HttpOnly"),
    ("set-cookie", "mid=mid-abc; Path=/; Domain=.mihoyo.com"),
    ("set-cookie", "stuid=100000001; Path=/; Domain=.mihoyo.com"),
]


def _auth(handler) -> MihoyoQrAuth:
    return MihoyoQrAuth(transport=httpx.MockTransport(handler))


def test_create_login_success_and_headers() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["app_id"] = request.headers.get("x-rpc-app_id", "")
        captured["device_id"] = request.headers.get("x-rpc-device_id", "")
        assert request.url == httpx.URL(CREATE_URL)
        return httpx.Response(200, json={"retcode": 0, "message": "OK",
                                         "data": {"url": FAKE_URL, "ticket": "tk-1"}})

    ticket, url = asyncio.run(_auth(handler).create_login("rid-1"))
    assert ticket == "tk-1"
    assert url == FAKE_URL
    assert captured["app_id"] == "bll8iq97cem8"
    assert len(captured["device_id"]) >= 32  # uuid4


def test_create_login_failure_fixed_message() -> None:
    handler = lambda request: httpx.Response(200, json={"retcode": -3001, "message": "missing header"})
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_auth(handler).create_login("rid-2"))
    assert exc.value.code == ErrorCode.UPSTREAM_NETWORK
    assert str(exc.value) == "二维码生成失败，请稍后再试。"

    boom = lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
    with pytest.raises(DemiaogeError) as exc2:
        asyncio.run(_auth(boom).create_login("rid-3"))
    assert str(exc2.value) == "二维码生成失败，请稍后再试。"


def test_query_status_sequence_to_confirmed() -> None:
    state = {"n": 0}
    sequence = [
        {"retcode": 0, "message": "OK", "data": {"status": "Created", "user_info": None}},
        {"retcode": 0, "message": "OK", "data": {"status": "Scanned", "user_info": None}},
        {"retcode": 0, "message": "OK", "data": {"status": "Confirmed",
                                                 "user_info": {"aid": "100000001", "mid": "mid-abc"}}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(QUERY_URL)
        assert b'"ticket":"tk-1"' in request.read().replace(b" ", b"")
        body = sequence[min(state["n"], len(sequence) - 1)]
        state["n"] += 1
        if body["data"]["status"] == "Confirmed":
            return httpx.Response(200, json=body, headers=CONFIRMED_COOKIES)
        return httpx.Response(200, json=body)

    auth = _auth(handler)
    poll1, poll2, poll3 = asyncio.run(_run_sequence(auth))
    assert isinstance(poll1, QrPollResult) and poll1.status == "Created" and poll1.cookies is None
    assert poll2.status == "Scanned"
    assert poll3.status == "Confirmed"
    assert poll3.user_info == {"aid": "100000001", "mid": "mid-abc"}
    bundle = poll3.cookies
    assert bundle is not None
    assert bundle.cookie_token == "v2_ct_value"  # v2 名优先
    assert bundle.ltoken == "v2_lt_value"
    assert bundle.mid == "mid-abc"
    assert bundle.stuid == "100000001"
    assert bundle.ltuid == "100000001"  # cookie 缺失时回退 aid
    assert bundle.stoken == ""
    header = bundle.as_cookie_header()
    for piece in ("stuid=100000001", "mid=mid-abc", "ltoken=v2_lt_value",
                  "cookie_token=v2_ct_value", "ltuid=100000001"):
        assert piece in header
    assert "stoken=" not in header  # 空值字段跳过


async def _run_sequence(auth: MihoyoQrAuth) -> tuple[QrPollResult, QrPollResult, QrPollResult]:
    return (await auth.query_login("tk-1", "rid"),
            await auth.query_login("tk-1", "rid"),
            await auth.query_login("tk-1", "rid"))


@pytest.mark.parametrize("code,expected", [
    (-3501, "Expired"),
    (-3505, "Cancelled"),
    (-3503, "Risk"),
    (-9999, "Risk"),
])
def test_query_error_code_mapping(code: int, expected: str) -> None:
    handler = lambda request: httpx.Response(200, json={"retcode": code, "message": "x", "data": None})
    result = asyncio.run(_auth(handler).query_login("tk-1", "rid"))
    assert result.status == expected
    assert result.cookies is None


def test_query_unknown_status_treated_as_risk() -> None:
    handler = lambda request: httpx.Response(
        200, json={"retcode": 0, "message": "OK", "data": {"status": "WeirdStatus"}})
    result = asyncio.run(_auth(handler).query_login("tk-1", "rid"))
    assert result.status == "Risk"


def test_cookie_header_skips_empty_and_joins_named() -> None:
    bundle = CookieBundle(stuid="42", stoken="v2_st", mid="m1", cookie_token="ct1")
    assert bundle.as_cookie_header() == "stuid=42; stoken=v2_st; mid=m1; cookie_token=ct1"
    assert CookieBundle().as_cookie_header() == ""


def test_complete_with_stoken_fills_missing_tokens() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cookie"] = request.headers.get("Cookie", "")
        if request.url.path.endswith("getCookieAccountInfoBySToken"):
            return httpx.Response(200, json={"retcode": 0, "message": "OK",
                                             "data": {"cookie_token": "ct_from_st"}})
        if request.url.path.endswith("getLTokenBySToken"):
            return httpx.Response(200, json={"retcode": 0, "message": "OK",
                                             "data": {"token": "lt_from_st"}})
        raise AssertionError(request.url)

    auth = _auth(handler)
    bundle = CookieBundle(stuid="100000001", stoken="v2_st", mid="mid-abc")
    filled = asyncio.run(auth.complete_with_stoken(bundle, "rid-4"))
    assert filled.cookie_token == "ct_from_st"
    assert filled.ltoken == "lt_from_st"
    assert filled.stoken == "v2_st" and filled.mid == "mid-abc" and filled.stuid == "100000001"
    assert "mid=mid-abc" in seen["cookie"] and "stoken=v2_st" in seen["cookie"]
    assert bundle.cookie_token == ""  # 原 bundle 不被就地修改


def test_complete_with_stoken_silent_failure() -> None:
    handler = lambda request: httpx.Response(200, json={"retcode": -100, "message": "bad"})
    auth = _auth(handler)
    bundle = CookieBundle(stuid="1", stoken="v2_st", mid="m1")
    filled = asyncio.run(auth.complete_with_stoken(bundle, "rid-5"))
    assert filled == bundle  # 失败静默保留原 bundle，不抛异常

    no_stoken = CookieBundle(stuid="1")
    assert asyncio.run(auth.complete_with_stoken(no_stoken, "rid-6")) is no_stoken
