"""请求体大小门禁与 Host 校验（BR-18、BR-69）。"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any, Callable, Set

from starlette.datastructures import Headers

from runtimes.ming_tts.errors import invalid, payload_too_large
from runtimes.ming_tts.schema import MAX_BODY_BYTES


class BodyTooLargeError(Exception):
    """读取正文过程中超过上限。"""


class BodyLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > self.max_bytes
        ):
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

    async def _reject(self, send: Callable) -> None:
        error = payload_too_large()
        body = json.dumps(error.payload(), ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": error.status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _local_addresses() -> Set[str]:
    """本机回环与局域网地址；用于 0.0.0.0 监听时的 Host 白名单。"""
    addresses = {"127.0.0.1", "::1", "localhost"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addresses.add(info[4][0])
        for address in socket.gethostbyname_ex(hostname)[2]:
            addresses.add(address)
    except OSError:
        pass
    return addresses


def _strip_port(host: str) -> str:
    value = host.strip()
    if value.startswith("["):
        end = value.find("]")
        if end != -1:
            return value[1:end]
    if value.lower().startswith("localhost:"):
        return "localhost"
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


class HostValidationMiddleware:
    """只接受回环地址与本机地址，防止 DNS rebinding（BR-69）。"""

    def __init__(self, app: Any, addresses: Set[str] | None = None) -> None:
        self.app = app
        self.addresses = addresses or _local_addresses()

    async def __call__(self, scope: Any, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = Headers(scope=scope).get("host")
        if host and not self._allowed(host):
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, host: str) -> bool:
        value = _strip_port(host).lower()
        if not value:
            return True
        # 0.0.0.0 是监听地址，不是合法 Host 值
        if value == "0.0.0.0":
            return False
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return value == "localhost"
        return address.is_loopback or value in self.addresses

    async def _reject(self, send: Callable) -> None:
        error = invalid("Host 头不被允许")
        body = json.dumps(error.payload(), ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": error.status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

