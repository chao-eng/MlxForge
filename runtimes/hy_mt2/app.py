"""OpenAI 兼容的 Hy-MT2 翻译服务。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any, List, Optional

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from runtimes.hy_mt2.model_manager import ModelManager

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, "models", "hy-mt2", "4bit")
DEFAULT_IDLE_TIMEOUT = 1200


class ChatRequest(BaseModel):
    model: str = "Hy-MT2"
    messages: List[dict]
    stream: bool = False
    max_tokens: Optional[int] = 4096
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.6
    top_k: Optional[int] = 20
    repetition_penalty: Optional[float] = 1.05


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
    """按中文单字、英文单词和标点切块，供 SSE 下发使用。"""
    pattern = r"[\u4e00-\u9fa5]|\b[A-Za-z0-9_'\-]+\b|[^\w\s]|[\s]+"
    return re.findall(pattern, text) or [text]


def stream_chunks(text: str, model_name: str):
    chat_id = "chatcmpl-" + str(uuid.uuid4())
    created = int(time.time())
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
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def create_app(
    model_path: Optional[str] = None,
    idle_timeout: Optional[int] = None,
) -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    manager = ModelManager(
        model_path=model_path or os.environ.get("HY_MT2_MODEL_PATH", DEFAULT_MODEL_PATH),
        idle_timeout=idle_timeout
        if idle_timeout is not None
        else int(os.environ.get("HY_MT2_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)),
    )

    app = FastAPI(title="Hy-MT2 OpenAI API")
    app.state.manager = manager

    @app.post("/v1/chat/completions")
    async def chat(request: ChatRequest):
        prompt = build_prompt(request.messages, manager.tokenizer())
        result = manager.generate(
            prompt,
            max_tokens=request.max_tokens or 4096,
            temperature=request.temperature if request.temperature is not None else 0.7,
            top_p=request.top_p if request.top_p is not None else 0.6,
            top_k=request.top_k if request.top_k is not None else 20,
            repetition_penalty=request.repetition_penalty
            if request.repetition_penalty is not None
            else 1.05,
        )

        if request.stream:
            return StreamingResponse(
                stream_chunks(result, request.model),
                media_type="text/event-stream",
            )

        return {
            "id": "chatcmpl-" + str(uuid.uuid4()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result},
                    "finish_reason": "stop",
                }
            ],
        }

    @app.get("/v1/models")
    async def models():
        return {
            "object": "list",
            "data": [{"id": "Hy-MT2", "object": "model"}],
        }

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "model_loaded": manager.is_loaded,
            "idle_seconds": round(manager.idle_seconds, 1),
            "idle_timeout_seconds": manager.idle_timeout,
        }

    return app
