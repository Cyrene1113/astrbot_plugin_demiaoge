"""米哈游 DS 签名（纯函数，离线可测）。

公式与 salt 出处见 ``docs/api_notes.md`` §3（W1-A 三源交叉验证）：
- 头格式固定为 ``{t},{r},{sign}``，``t`` 为秒级时间戳，``r`` 为 6 位数字（100000-200000）。
- 简单式：``sign = md5("salt={salt}&t={t}&r={r}")``（bbs 签到 / stoken 兑换等）。
- b/q 式：``sign = md5("salt={salt}&t={t}&r={r}&b={body}&q={query}")``，**b 在 q 前**；
  game_record 全部端点与 passport app 变体使用。GET 时 ``b=""`` 且 ``q`` 为按参数名
  字母序排列的 query 串；POST 时 ``b=JSON 字符串``（空对象为 ``"{}"``）且 ``q=""``。
"""

from __future__ import annotations

import hashlib
import secrets
import time

# game_record（hkrpg/genshin，CN）——Miao-Yunzai / MihoyoBBSTools / mystool 三源一致
SALT_X4 = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
# passport app 变体（xiaoyao passSalt / mystool SALT_PROD / UIGF 汇总），W1-A 实测通过
SALT_PROD = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"


def _now_t() -> int:
    return int(time.time())


def _random_r() -> str:
    """6 位数字随机 r，取值范围 [100000, 200000]（各家实现一致的约定）。"""
    return str(100000 + secrets.randbelow(100001))


def ds_simple(salt: str, t: int | None = None, r: str | int | None = None) -> str:
    """简单式 DS 头：md5("salt={salt}&t={t}&r={r}")。返回 ``{t},{r},{sign}``。"""
    t = _now_t() if t is None else int(t)
    r = _random_r() if r is None else str(r)
    sign = hashlib.md5(f"salt={salt}&t={t}&r={r}".encode("utf-8")).hexdigest()
    return f"{t},{r},{sign}"


def ds_bq(salt: str, body: str = "", query: str = "", t: int | None = None,
          r: str | int | None = None) -> str:
    """b/q 式 DS 头：md5("salt={salt}&t={t}&r={r}&b={body}&q={query}")，b 在 q 前。

    - POST：``body`` 传 JSON 字符串（空对象传 ``"{}"``），``query`` 传 ``""``。
    - GET：``body`` 传 ``""``，``query`` 传按参数名字母序排列的 ``k=v&k=v`` 串。
    """
    t = _now_t() if t is None else int(t)
    r = _random_r() if r is None else str(r)
    sign = hashlib.md5(f"salt={salt}&t={t}&r={r}&b={body}&q={query}".encode("utf-8")).hexdigest()
    return f"{t},{r},{sign}"
