"""参考音频临时文件：安全创建、启动清理与删除（BR-61、BR-84、BR-85、BR-97）。

只操作本程序命名的文件，不递归删除目录内容；目录无法安全创建或确认归属时，
`available` 为 False，克隆请求由调用方返回 503。
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FILE_PREFIX = "ming-tts-ref-"
FILE_SUFFIX = ".audio"
MAX_NAME_LENGTH = 200


class TempStorageError(RuntimeError):
    """临时目录不可用，调用方应返回 503。"""


class TempAudioStore:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self._real_dir: Optional[Path] = None
        self._dir_fd: Optional[int] = None
        self._error: Optional[str] = None

    @property
    def available(self) -> bool:
        return self._dir_fd is not None

    @property
    def error(self) -> Optional[str]:
        return self._error

    def prepare(self) -> None:
        """启动时调用一次；失败只记录原因，不阻止服务启动。"""
        try:
            base = self.base_dir
            if base.is_symlink():
                raise RuntimeError("临时目录不能是符号链接")
            if base.exists():
                info = os.lstat(base)
                if not stat.S_ISDIR(info.st_mode):
                    raise RuntimeError("临时路径不是目录")
            else:
                base.mkdir(mode=0o700, parents=True)
            real = base.resolve(strict=True)
            info = os.stat(real)
            if info.st_uid != os.getuid():
                raise RuntimeError("临时目录所有者不是当前用户")
            os.chmod(real, 0o700)
            dir_fd = os.open(real, os.O_RDONLY | os.O_DIRECTORY)
            self._real_dir = real
            self._dir_fd = dir_fd
            self._cleanup_leftovers()
            logger.info("参考音频临时目录就绪：%s", real)
        except (OSError, RuntimeError) as exc:
            self._error = f"参考音频临时目录不可用：{type(exc).__name__}"
            logger.warning("%s（%s）", self._error, exc)
            self.close()

    def create(self, request_id: str) -> str:
        """创建一个 0600 的独立文件，返回文件名。"""
        dir_fd = self._require_fd()
        name = f"{FILE_PREFIX}{request_id}-{secrets.token_hex(4)}{FILE_SUFFIX}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(name, flags, 0o600, dir_fd=dir_fd)
        os.close(descriptor)
        return name

    def write(self, name: str, data: bytes) -> None:
        dir_fd = self._require_fd()
        if not self._is_own_name(name):
            raise TempStorageError("临时文件名不合法")
        descriptor = os.open(name, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        try:
            with os.fdopen(descriptor, "wb") as writer:
                writer.write(data)
        except OSError as exc:
            raise TempStorageError("参考音频临时文件写入失败") from exc

    def path(self, name: str) -> Path:
        if self._real_dir is None or not self._is_own_name(name):
            raise TempStorageError("参考音频临时文件不可用")
        return self._real_dir / name

    def remove(self, name: Optional[str]) -> None:
        """删除本程序创建的文件；重复调用与文件缺失都安全。"""
        if not name or self._dir_fd is None or not self._is_own_name(name):
            return
        try:
            info = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                return
            os.unlink(name, dir_fd=self._dir_fd)
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("删除参考音频临时文件失败：%s", type(exc).__name__)

    def close(self) -> None:
        if self._dir_fd is not None:
            try:
                os.close(self._dir_fd)
            except OSError:
                pass
        self._dir_fd = None
        self._real_dir = None

    # ---------- 内部 ----------

    def _require_fd(self) -> int:
        if self._dir_fd is None:
            raise TempStorageError("参考音频临时目录不可用")
        return self._dir_fd

    def _cleanup_leftovers(self) -> None:
        """只清理本程序命名的普通文件，不递归、不碰目录外内容。"""
        dir_fd = self._require_fd()
        for name in os.listdir(dir_fd):
            if not self._is_own_name(name):
                continue
            try:
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    continue
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("清理遗留临时文件失败：%s", type(exc).__name__)

    @staticmethod
    def _is_own_name(name: str) -> bool:
        return (
            len(name) <= MAX_NAME_LENGTH
            and name.startswith(FILE_PREFIX)
            and name.endswith(FILE_SUFFIX)
            and "/" not in name
            and "\\" not in name
        )
