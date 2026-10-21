"""OpenAI 兼容的 Hy-MT2 翻译服务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import uuid
from concurrent.futures import Future
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from runtimes.hy_mt2.model_manager import (
    ModelLoadError,
    ModelManager,
    QueueFullError,
    ServiceClosedError,
)

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, "models", "hy-mt2", "4bit")
DEFAULT_IDLE_TIMEOUT = 1200
DEFAULT_MAX_QUEUE = 8
MAX_BODY_BYTES = 1024 * 1024
SHUTDOWN_GRACE_SECONDS = 30.0
WEB_DIST = os.path.join(REPO_ROOT, "web", "dist")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class BodyTooLargeError(Exception):
    """请求体超过上限。"""


class ClientDisconnected(Exception):
    """客户端在等待结果时断开。"""


class BodyLimitMiddleware:
    """在解析请求体之前拦住超过 1MB 的请求。"""

    def __init__(self, app: Any, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            await self._reject(send)
            return

        received = 0

        async def limited_receive() -> Any:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLargeError:
            await self._reject(send)

    async def _reject(self, send: Any) -> None:
        payload = json.dumps(
            {
                "error": {
                    "type": "payload_too_large",
                    "message": "请求体超过 1MB，请缩短原文",
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class RequestIdMiddleware:
    """给每个 HTTP 请求分配短标识，日志据此定位单次请求。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["request_id"] = uuid.uuid4().hex[:8]
        await self.app(scope, receive, send)


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def check_role(cls, value: str) -> str:
        if value not in {"system", "user", "assistant"}:
            raise ValueError("role 只支持 system、user、assistant")
        return value


class ChatRequest(BaseModel):
    model: str = "Hy-MT2"
    messages: List[ChatMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int = Field(default=4096, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.6, ge=0, le=1)
    top_k: int = Field(default=20, ge=0, le=100)
    repetition_penalty: float = Field(default=1.05, ge=0.5, le=2.0)


def build_prompt(messages: List[dict], tokenizer: Any) -> str:
    """优先使用官方 chat_template，拿不到时退化成纯文本拼接。"""
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=False,
        )
    return "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "user"
    ).strip()


def split_chunks(text: str) -> List[str]:
    """按中文单字、词、标点切块，供 SSE 下发使用，必须保证不丢字符。"""
    # 末两项兜底覆盖所有字符：\w 之外的标点和空白之外的单字符也要发出去，
    # 否则日文假名、韩文、西里尔字母等非 ASCII 文字会在流式输出里被吞掉
    pattern = r"[\u4e00-\u9fa5]|\w+|\s+|[^\w\s]"
    return re.findall(pattern, text) or [text]


def stream_chunks(text: str, model_name: str, finish_reason: str) -> AsyncIterator[str]:
    chat_id = "chatcmpl-" + str(uuid.uuid4())
    created = int(time.time())

    async def generator() -> AsyncIterator[str]:
        for token in split_chunks(text):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason,
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return generator()


def error_event(error_type: str, message: str) -> AsyncIterator[str]:
    async def generator() -> AsyncIterator[str]:
        payload = {"error": {"type": error_type, "message": message}}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return generator()


def error_response(
    status_code: int,
    error_type: str,
    message: str,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message}},
        headers=headers,
    )


async def await_future(request: Request, future: Future) -> Any:
    """等待推理结果，同时轮询客户端是否断开。"""
    task = asyncio.wrap_future(future)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.2)
            if task in done:
                return task.result()
            if await request.is_disconnected():
                task.cancel()
                raise ClientDisconnected
    finally:
        if not task.done():
            task.cancel()


def _force_exit() -> None:
    logger.error("优雅退出超过 %.0f 秒，强制结束进程", SHUTDOWN_GRACE_SECONDS)
    os._exit(1)


def reject_multi_workers() -> None:
    """uvicorn 多 worker 会各自占一份内存，必须在启动时拦住。"""
    for index, arg in enumerate(sys.argv):
        if arg == "--workers" and index + 1 < len(sys.argv):
            value = sys.argv[index + 1]
        elif arg.startswith("--workers="):
            value = arg.split("=", 1)[1]
        else:
            continue
        if value.isdigit() and int(value) > 1:
            raise RuntimeError("只允许单 worker 运行，请去掉 --workers 或设为 1")


def create_app(
    model_path: Optional[str] = None,
    idle_timeout: Optional[int] = None,
) -> FastAPI:
    log_level = os.environ.get("HY_MT2_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    reject_multi_workers()

    resolved_timeout = (
        idle_timeout
        if idle_timeout is not None
        else int(os.environ.get("HY_MT2_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT))
    )
    max_queue = int(os.environ.get("HY_MT2_MAX_QUEUE", DEFAULT_MAX_QUEUE))
    manager = ModelManager(
        model_path=model_path or os.environ.get("HY_MT2_MODEL_PATH", DEFAULT_MODEL_PATH),
        idle_timeout=resolved_timeout,
        max_queue=max_queue,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # uvicorn 自己处理 SIGTERM，这里包一层，先让排队请求失败再走优雅退出
        previous_handlers: dict[int, Any] = {}
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                previous_handlers[signum] = signal.getsignal(signum)

                def handler(
                    received: int,
                    frame: Any,
                    _previous: Any = previous_handlers[signum],
                ) -> None:
                    manager.begin_shutdown()
                    # 在途生成超过 30 秒仍未结束时强制退出，避免进程挂住
                    timer = threading.Timer(SHUTDOWN_GRACE_SECONDS, _force_exit)
                    timer.daemon = True
                    timer.start()
                    if callable(_previous):
                        _previous(received, frame)

                signal.signal(signum, handler)
            except (ValueError, OSError):
                logger.debug("信号 %s 处理注册失败", signum)
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(title="Hy-MT2 OpenAI API", lifespan=lifespan)
    app.state.manager = manager
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BodyLimitMiddleware)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        field = ""
        if errors:
            loc = [str(part) for part in errors[0].get("loc", ()) if part != "body"]
            field = ".".join(loc)
        logger.info(
            "请求校验失败 request_id=%s type=invalid_request_error field=%s",
            request_id(request),
            field or "-",
        )
        message = f"请求字段不合法：{field}" if field else "请求字段不合法"
        return error_response(400, "invalid_request_error", message)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping = {
            404: ("not_found", "接口不存在"),
            405: ("method_not_allowed", "请求方法不允许"),
        }
        if exc.status_code in mapping:
            error_type, message = mapping[exc.status_code]
        elif 400 <= exc.status_code < 500:
            error_type, message = "invalid_request_error", str(exc.detail)
        else:
            error_type, message = "internal_error", "服务内部错误"
        return error_response(exc.status_code, error_type, message)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "未预期异常 request_id=%s type=internal_error：%s",
            request_id(request),
            exc,
        )
        return error_response(500, "internal_error", "服务内部错误")

    @app.post("/v1/chat/completions")
    async def chat(request: Request, payload: ChatRequest) -> Response:
        messages = [message.model_dump() for message in payload.messages]

        try:
            input_tokens = manager.count_message_tokens(messages)
        except ModelLoadError as exc:
            logger.warning(
                "tokenizer 不可用 request_id=%s type=model_unavailable：%s",
                request_id(request),
                exc,
            )
            return error_response(503, "model_unavailable", str(exc))

        limit = manager.context_limit()
        if limit is not None and input_tokens + payload.max_tokens > limit:
            return error_response(
                400,
                "invalid_request_error",
                "原文太长，请分段翻译",
            )

        prompt = build_prompt(messages, manager.tokenizer())

        try:
            future = manager.submit_generate(
                prompt,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                top_p=payload.top_p,
                top_k=payload.top_k,
                repetition_penalty=payload.repetition_penalty,
            )
        except QueueFullError:
            return error_response(
                429,
                "queue_full",
                "当前请求太多，请稍后重试",
                {"Retry-After": "1"},
            )
        except (ModelLoadError, ServiceClosedError) as exc:
            return error_response(503, "model_unavailable", str(exc))

        try:
            result = await await_future(request, future)
        except ClientDisconnected:
            manager.cancel(future)
            return Response(status_code=204)
        except (ModelLoadError, ServiceClosedError) as exc:
            logger.warning(
                "生成不可用 request_id=%s type=model_unavailable：%s",
                request_id(request),
                exc,
            )
            if payload.stream:
                return StreamingResponse(
                    error_event("model_unavailable", str(exc)),
                    media_type="text/event-stream",
                    headers=SSE_HEADERS,
                )
            return error_response(503, "model_unavailable", str(exc))
        except Exception as exc:
            logger.exception(
                "生成失败 request_id=%s type=internal_error：%s",
                request_id(request),
                exc,
            )
            if payload.stream:
                return StreamingResponse(
                    error_event("internal_error", "服务内部错误"),
                    media_type="text/event-stream",
                    headers=SSE_HEADERS,
                )
            return error_response(500, "internal_error", "服务内部错误")

        if payload.stream:
            return StreamingResponse(
                stream_chunks(result.text, payload.model, result.finish_reason),
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )

        return {
            "id": "chatcmpl-" + str(uuid.uuid4()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.text},
                    "finish_reason": result.finish_reason,
                }
            ],
        }

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": "Hy-MT2", "object": "model", "owned_by": "local"}],
        }

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return manager.snapshot()

    if os.path.isdir(WEB_DIST):
        # 只挂 assets 和首页，避免通配挂载吞掉 API 的 405
        assets_dir = os.path.join(WEB_DIST, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(os.path.join(WEB_DIST, "index.html"))
    else:
        logger.warning("未找到 %s，Web UI 不可用，请先在 web/ 执行 pnpm build", WEB_DIST)

        @app.get("/")
        async def index_missing() -> JSONResponse:
            return error_response(
                503,
                "model_unavailable",
                "Web UI 尚未构建，请先在 web/ 执行 pnpm build",
            )

    return app
