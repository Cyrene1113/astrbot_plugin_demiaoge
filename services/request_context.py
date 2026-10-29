"""请求上下文：生成并传递 request_id，日志不得携带敏感参数。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    request_id: str

    @classmethod
    def create(cls) -> "RequestContext":
        return cls(uuid.uuid4().hex[:12])

    def log(self, logger: logging.Logger, level: int, message: str, *args: object) -> None:
        logger.log(level, "[request_id=%s] " + message, self.request_id, *args)
