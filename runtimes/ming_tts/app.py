"""Ming-3.0-tts 的 FastAPI 入口（UC-04、UC-06）。

只负责 HTTP 层的参数校验、入队与响应组装；模型生命周期在 `model_manager.py`，
重 CPU/IO 操作全部交给线程池（BR-98）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from runtimes.ming_tts import audio
from runtimes.ming_tts.audio import ReferenceAudioError, inspect_reference
from runtimes.ming_tts.errors import (
    install_error_handlers,
    internal,
    invalid,
    model_unavailable,
    queue_full,
)
from runtimes.ming_tts.middleware import BodyLimitMiddleware, HostValidationMiddleware
from runtimes.ming_tts.model_manager import (
    ModelManager,
    ModelUnavailableError,
    QueueFullError,
    QueueTimeoutError,
    RequestCancelledError,
    ServiceClosedError,
)
from runtimes.ming_tts.schema import SpeechRequest, parse_speech_request
from runtimes.ming_tts.synth import SynthesisResult, synthesize
from runtimes.ming_tts.tasks import ResolvedTask, resolve_task
from runtimes.ming_tts.tempfiles import TempAudioStore, TempStorageError

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, "models", "ming-tts", "8bit")
WEB_DIST = os.path.join(REPO_ROOT, "web", "dist")
DEFAULT_IDLE_TIMEOUT = 1200
DEFAULT_MAX_QUEUE = 8
DEFAULT_QUEUE_TIMEOUT = 120
DEFAULT_LOG_LEVEL = "INFO"
SHUTDOWN_GRACE_SECONDS = 120.0
# 客户端断开轮询间隔，兼顾响应及时性与空转开销
DISCONNECT_POLL_SECONDS = 0.5
MODEL_ID = "Ming-3.0-tts"


class Settings:
    def __init__(self) -> None:
        self.model_path = os.environ.get("MING_TTS_MODEL_PATH", DEFAULT_MODEL_PATH)
        self.idle_timeout = _env_int("MING_TTS_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)
        self.max_queue = _env_int("MING_TTS_MAX_QUEUE", DEFAULT_MAX_QUEUE)
        self.queue_timeout = _env_float(
            "MING_TTS_QUEUE_TIMEOUT", DEFAULT_QUEUE_TIMEOUT
        )
        self.temp_dir = os.environ.get(
            "MING_TTS_TEMP_DIR", os.path.join(tempfile.gettempdir(), "ming-tts")
        )
        self.log_level = os.environ.get("MING_TTS_LOG_LEVEL", DEFAULT_LOG_LEVEL)

        if self.idle_timeout < 0:
            raise RuntimeError("MING_TTS_IDLE_TIMEOUT 不能为负数")
        if self.max_queue < 0:
            raise RuntimeError("MING_TTS_MAX_QUEUE 不能为负数")
        if self.queue_timeout <= 0:
            raise RuntimeError("MING_TTS_QUEUE_TIMEOUT 必须大于 0")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数字") from exc


def _configure_logging(level_name: str) -> None:
    level = logging.getLevelNamesMapping().get(level_name.upper())
    if level is None:
        raise RuntimeError(f"MING_TTS_LOG_LEVEL 不是合法级别：{level_name}")
    logging.getLogger("runtimes.ming_tts").setLevel(level)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def create_app() -> FastAPI:
    settings = Settings()
    _configure_logging(settings.log_level)

    manager = ModelManager(
        settings.model_path,
        idle_timeout=settings.idle_timeout,
        max_queue=settings.max_queue,
        queue_timeout=settings.queue_timeout,
    )
    store = TempAudioStore(settings.temp_dir)
    store.prepare()
    started_at = int(time.time())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "服务启动：模型目录 %s，空闲阈值 %s 秒，等待上限 %s",
            settings.model_path,
            settings.idle_timeout,
            settings.max_queue,
        )
        yield
        await run_in_threadpool(manager.shutdown, SHUTDOWN_GRACE_SECONDS)
        store.close()
        logger.info("服务已停止")

    app = FastAPI(title="MlxForge Ming-3.0-tts", lifespan=lifespan)
    app.state.manager = manager
    app.state.temp_store = store

    # 后添加的中间件在最外层：先校验 Host，再限制请求体
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(HostValidationMiddleware)
    install_error_handlers(app)

    @app.post("/v1/audio/speech")
    async def create_speech(request: Request) -> Response:
        request_id = str(uuid.uuid4())
        short_id = request_id[:8]
        started = time.monotonic()

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise invalid("请求体不是合法的 JSON") from exc

        speech = parse_speech_request(payload)
        task = resolve_task(speech)
        logger.debug(
            "请求 %s：task=%s，文本 %d 码点，参考音频 %s",
            short_id,
            task.model_task,
            len(speech.input),
            "有" if speech.has_reference else "无",
        )

        reference_name = await _prepare_reference(
            store, speech, request_id
        )
        result = await _run_synthesis(
            manager, store, speech, task, reference_name, short_id, request
        )

        if speech.response_format == "wav":
            body = await run_in_threadpool(audio.encode_wav, result.pcm)
            media_type = "audio/wav"
        else:
            body = result.pcm
            media_type = "audio/pcm"

        logger.info(
            "请求 %s 完成：task=%s，音频 %.2f 秒，耗时 %.2f 秒",
            short_id,
            task.model_task,
            result.duration,
            time.monotonic() - started,
        )
        return Response(
            content=body,
            media_type=media_type,
            headers=_response_headers(request_id, speech, task, result),
        )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(manager.snapshot())

    @app.get("/v1/models")
    async def list_models() -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": MODEL_ID,
                    "object": "model",
                    "created": started_at,
                    "owned_by": "mlxforge",
                }
            ],
        }

    _mount_web_ui(app)
    return app


def _mount_web_ui(app: FastAPI) -> None:
    """把 `web/dist` 挂到同源 `/`（BR-68），未构建时给出可读提示。"""
    if os.path.isdir(WEB_DIST):
        assets_dir = os.path.join(WEB_DIST, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def index(request: Request) -> Response:
            # 单模型启动时直接把入口固定到语音合成，避免前端先渲染默认页再跳转；
            # 已带 page 参数时必须直接返回页面，否则会重定向到自己形成死循环
            if "page" not in request.query_params:
                return RedirectResponse(url="/?page=tts", status_code=307)
            return FileResponse(os.path.join(WEB_DIST, "index.html"))

        return

    logger.warning("未找到 %s，Web UI 不可用，请先在 web/ 执行 pnpm build", WEB_DIST)

    @app.get("/", include_in_schema=False)
    async def index_missing() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "type": "model_unavailable",
                    "message": "Web UI 尚未构建，请先在 web/ 执行 pnpm build",
                }
            },
        )


async def _prepare_reference(
    store: TempAudioStore, speech: SpeechRequest, request_id: str
) -> Optional[str]:
    """base64 解码、容器校验与临时文件写入都在线程池完成（BR-98）。"""
    if not speech.has_reference:
        return None
    if not store.available:
        raise model_unavailable("参考音频临时目录不可用，声音克隆暂不可用")

    def work() -> str:
        try:
            data = base64.b64decode(speech.reference_audio, validate=True)
        except (ValueError, TypeError) as exc:
            raise ReferenceAudioError("参考音频不是合法的 base64") from exc
        inspect_reference(data)
        try:
            name = store.create(request_id)
            store.write(name, data)
        except TempStorageError as exc:
            raise TempStorageError(str(exc)) from exc
        return name

    try:
        return await run_in_threadpool(work)
    except ReferenceAudioError as exc:
        raise invalid(str(exc)) from exc
    except TempStorageError as exc:
        raise model_unavailable("参考音频临时目录不可用，声音克隆暂不可用") from exc


async def _run_synthesis(
    manager: ModelManager,
    store: TempAudioStore,
    speech: SpeechRequest,
    task: ResolvedTask,
    reference_name: Optional[str],
    short_id: str,
    request: Request,
) -> SynthesisResult:
    """入队、等待结果，并按 BR-97 划分临时文件删除权。"""

    def call(model: Any) -> SynthesisResult:
        # 正常流程由 worker 读取后删除；无论成功失败都在 finally 清理
        try:
            path = store.path(reference_name) if reference_name else None
            return synthesize(model, speech, task, path)
        finally:
            store.remove(reference_name)

    def discard_reference() -> None:
        store.remove(reference_name)

    try:
        job = manager.submit(call)
    except QueueFullError as exc:
        discard_reference()
        raise queue_full("等待队列已满，请稍后重试") from exc
    except ModelUnavailableError as exc:
        discard_reference()
        raise model_unavailable() from exc
    except ServiceClosedError as exc:
        discard_reference()
        raise model_unavailable("服务正在停止") from exc

    # uvicorn 不会因客户端断开而取消 handler，必须主动轮询 http.disconnect（BR-59）
    wait_task = asyncio.create_task(run_in_threadpool(manager.wait, job))
    drop_checked = False
    try:
        while True:
            done, _ = await asyncio.wait({wait_task}, timeout=DISCONNECT_POLL_SECONDS)
            if wait_task in done:
                return wait_task.result()
            if not drop_checked and await request.is_disconnected():
                drop_checked = True
                # 只有确认仍在队列时才由 handler 删除参考音频（BR-97）
                cancelled = manager.cancel(job)
                if cancelled:
                    discard_reference()
                logger.info(
                    "请求 %s 客户端已断开：%s",
                    short_id,
                    "排队任务已取消" if cancelled else "在途任务继续，完成后丢弃结果",
                )
    except asyncio.CancelledError:
        # 服务关闭时取消：排队中则移出队列并回收临时文件；在途交给 worker
        if manager.cancel(job):
            discard_reference()
        raise
    except QueueTimeoutError as exc:
        discard_reference()
        raise queue_full("排队等待超时，请稍后重试") from exc
    except RequestCancelledError as exc:
        discard_reference()
        raise model_unavailable("请求已取消") from exc
    except ModelUnavailableError as exc:
        discard_reference()
        raise model_unavailable() from exc
    except ServiceClosedError as exc:
        discard_reference()
        raise model_unavailable("服务正在停止") from exc
    except Exception as exc:
        # worker 内的合成异常已在 finally 删除临时文件，这里重复删除是幂等的
        discard_reference()
        logger.error("请求 %s 合成失败：%s", short_id, type(exc).__name__)
        raise internal() from exc
    finally:
        if not wait_task.done():
            wait_task.cancel()


def _response_headers(
    request_id: str,
    speech: SpeechRequest,
    task: ResolvedTask,
    result: SynthesisResult,
) -> Dict[str, str]:
    extension = "wav" if speech.response_format == "wav" else "pcm"
    return {
        "X-Request-Id": request_id,
        "X-Resolved-Task": task.model_task,
        "X-Seed": str(speech.seed),
        "X-Audio-Sample-Rate": str(audio.SAMPLE_RATE),
        "X-Audio-Bits": str(audio.BITS_PER_SAMPLE),
        "X-Audio-Channels": str(audio.CHANNELS),
        "X-Audio-Byte-Order": "little",
        "X-Audio-Duration": f"{result.duration:.2f}",
        "X-Audio-Format": speech.response_format,
        "Content-Disposition": f'attachment; filename="speech-{request_id}.{extension}"',
        "Cache-Control": "no-store",
    }
