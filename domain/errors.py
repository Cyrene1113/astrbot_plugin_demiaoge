"""德谬歌领域错误码与异常。"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CMD_INVALID = "CMD_INVALID"
    AUTH_MISSING = "AUTH_MISSING"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    MAPPING_FAILED = "MAPPING_FAILED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_NETWORK = "UPSTREAM_NETWORK"
    UPSTREAM_SCHEMA = "UPSTREAM_SCHEMA"
    DATA_NOT_FOUND = "DATA_NOT_FOUND"
    STORAGE_FAILED = "STORAGE_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    INTERNAL = "INTERNAL"


class DemiaogeError(Exception):
    """可安全展示给用户的业务异常；message 不得包含凭据或上游原文。"""

    def __init__(self, code: ErrorCode, message: str, request_id: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message  # 与 str(exc) 等值，便于规范化取文案（不改展示行为）
        self.request_id = request_id


class CookieExpiredError(DemiaogeError):
    def __init__(self, request_id: str = "") -> None:
        super().__init__(ErrorCode.AUTH_EXPIRED, "绑定凭据已失效，请重新绑定。", request_id)


class RateLimitedError(DemiaogeError):
    def __init__(self, request_id: str = "") -> None:
        super().__init__(ErrorCode.RATE_LIMITED, "请求过于频繁，请稍后再试。", request_id)


class MappingError(DemiaogeError):
    def __init__(self, request_id: str = "") -> None:
        super().__init__(ErrorCode.MAPPING_FAILED, "上游数据格式暂不兼容。", request_id)
