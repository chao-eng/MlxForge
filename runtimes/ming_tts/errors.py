"""统一错误结构与 HTTP 状态映射（BR-45、BR-46、附录 A-4）。

错误类型是固定枚举，不允许在路由里临时拼新类型；中文 message 面向调用方，
不包含堆栈、路径或内部类型名，也不回显敏感文本。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

ERROR_INVALID_REQUEST = "invalid_request_error"
ERROR_PAYLOAD_TOO_LARGE = "payload_too_large"
ERROR_NOT_FOUND = "not_found"
ERROR_METHOD_NOT_ALLOWED = "method_not_allowed"
ERROR_QUEUE_FULL = "queue_full"
ERROR_MODEL_UNAVAILABLE = "model_unavailable"
ERROR_INTERNAL = "internal_error"

STATUS_BY_TYPE: Dict[str, int] = {
    ERROR_INVALID_REQUEST: 400,
    ERROR_PAYLOAD_TOO_LARGE: 413,
    ERROR_NOT_FOUND: 404,
    ERROR_METHOD_NOT_ALLOWED: 405,
    ERROR_QUEUE_FULL: 429,
    ERROR_MODEL_UNAVAILABLE: 503,
    ERROR_INTERNAL: 500,
}

QUEUE_RETRY_AFTER_SECONDS = 5


class ApiError(Exception):
    """业务错误，携带 HTTP 状态、错误类型与可选的响应头。"""

    def __init__(
        self,
        error_type: str,
        message: str,
        status_code: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status_code = status_code or STATUS_BY_TYPE[error_type]
        self.headers = headers

    def payload(self) -> Dict[str, Any]:
        return {"error": {"type": self.error_type, "message": self.message}}

    def response(self) -> JSONResponse:
        return JSONResponse(
            self.payload(), status_code=self.status_code, headers=self.headers
        )


def invalid(message: str) -> ApiError:
    return ApiError(ERROR_INVALID_REQUEST, message)


def payload_too_large() -> ApiError:
    return ApiError(ERROR_PAYLOAD_TOO_LARGE, "请求体超过 20MB，请缩短输入或参考音频")


def not_found() -> ApiError:
    return ApiError(ERROR_NOT_FOUND, "接口不存在")


def method_not_allowed() -> ApiError:
    return ApiError(ERROR_METHOD_NOT_ALLOWED, "请求方法不允许")


def queue_full(message: str = "等待队列已满，请稍后重试") -> ApiError:
    return ApiError(
        ERROR_QUEUE_FULL,
        message,
        headers={"Retry-After": str(QUEUE_RETRY_AFTER_SECONDS)},
    )


def model_unavailable(message: str = "语音合成模型当前不可用，请稍后重试") -> ApiError:
    return ApiError(ERROR_MODEL_UNAVAILABLE, message)


def internal(message: str = "合成失败，请稍后重试") -> ApiError:
    return ApiError(ERROR_INTERNAL, message)


def from_validation_error(exc: RequestValidationError) -> ApiError:
    """把 FastAPI 默认 422 收敛为 400，只保留字段名，不回显字段值（BR-45）。"""
    errors = exc.errors()
    if not errors:
        return invalid("请求参数不合法")

    first = errors[0]
    error_type = str(first.get("type", ""))
    location = [
        str(part)
        for part in first.get("loc", ())
        if part not in ("body", "query", "path")
    ]
    field = ".".join(location) or "请求体"

    if error_type == "json_invalid":
        message = "请求体不是合法的 JSON"
    elif error_type == "missing":
        message = f"缺少必填字段：{field}"
    elif error_type.endswith("_type"):
        message = f"字段 {field} 类型不正确"
    else:
        message = f"字段 {field} 不合法"
    return invalid(message)


def _from_http_exception(exc: StarletteHTTPException) -> ApiError:
    if exc.status_code == 404:
        error = not_found()
    elif exc.status_code == 405:
        error = method_not_allowed()
    elif exc.status_code == 413:
        error = payload_too_large()
    elif exc.status_code == 429:
        error = queue_full()
    elif 400 <= exc.status_code < 500:
        error = invalid(str(exc.detail) if exc.detail else "请求不合法")
    else:
        error = internal()

    if exc.headers:
        error.headers = {**(error.headers or {}), **exc.headers}
    return error


def install_error_handlers(app: FastAPI) -> None:
    """让所有错误都走同一结构；不把内部异常细节返回给调用方。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return from_validation_error(exc).response()

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _from_http_exception(exc).response()

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 只记录异常类型，异常消息可能带用户文本（BR-62）
        logger.error("未预期异常：%s", type(exc).__name__)
        return internal().response()
