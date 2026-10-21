"""Ming-3.0-tts 并发与队列验收（PRD §6.1、§6.5-18）。

两种场景各需不同的服务端队列配置，脚本只发请求并核对结果，不负责启动服务：

1. `capacity`：默认队列（`MING_TTS_MAX_QUEUE=8`），20 个并发 20 字请求，
   期望恰好 9 个 200（1 在途 + 8 排队）、11 个 429 且 `Retry-After: 5`
2. `timeout`：`MING_TTS_QUEUE_TIMEOUT` 调小（如 2 秒），9 个并发长文本请求，
   期望 1 个 200、8 个 429，且没有重复处理

用法：

    envs/ming-tts/bin/python scripts/test_ming_tts_concurrency.py --phase capacity
    envs/ming-tts/bin/python scripts/test_ming_tts_concurrency.py --phase timeout
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

SAMPLE_20 = "今天下午三点我们在楼下咖啡店见面聊聊天。"
SAMPLE_LONG = (
    "语音合成模型正在本地设备上运行，我们用它来朗读一段较长的中文文本，"
    "并观察实时率是否稳定，这条请求用于占满队列并触发排队超时。"
)
EXPECTED_RETRY_AFTER = "5"


def post(base: str, text: str) -> dict:
    body = json.dumps(
        {
            "model": "Ming-3.0-tts",
            "input": text,
            "voice": "auto",
            "language": "auto",
            "response_format": "wav",
            "seed": 7,
        },
        ensure_ascii=False,
    ).encode()
    request = urllib.request.Request(
        base + "/v1/audio/speech",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = response.read()
            return {
                "status": response.status,
                "elapsed": time.perf_counter() - started,
                "retry_after": response.headers.get("Retry-After"),
                "request_id": response.headers.get("X-Request-Id"),
                "content_disposition": response.headers.get("Content-Disposition"),
                "riff": payload[:4] == b"RIFF" and payload[8:12] == b"WAVE",
                "bytes": len(payload),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "elapsed": time.perf_counter() - started,
            "retry_after": exc.headers.get("Retry-After"),
            "request_id": exc.headers.get("X-Request-Id"),
            "body": exc.read()[:200].decode("utf-8", "replace"),
        }


def fire(base: str, text: str, count: int) -> list:
    barrier = threading.Barrier(count)
    results: list = [None] * count

    def worker(index: int) -> None:
        barrier.wait()
        results[index] = post(base, text)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def phase_capacity(base: str, count: int) -> bool:
    results = fire(base, SAMPLE_20, count)
    statuses = Counter(item["status"] for item in results)
    accepted = [item for item in results if item["status"] == 200]
    rejected = [item for item in results if item["status"] == 429]

    print(f"状态分布：{dict(statuses)}")
    checks = {
        "9 个成功": len(accepted) == 9,
        "11 个 429": len(rejected) == 11,
        "Retry-After 均为 5": all(
            item["retry_after"] == EXPECTED_RETRY_AFTER for item in rejected
        ),
        "成功响应均为完整 WAV": all(item["riff"] for item in accepted),
        "X-Request-Id 唯一": len({item["request_id"] for item in accepted}) == len(accepted),
        "响应头 request_id 与文件名一致": all(
            item["request_id"] in (item["content_disposition"] or "") for item in accepted
        ),
    }
    if rejected:
        print("429 错误体样例：", rejected[0].get("body", ""))
    return report(checks)


def phase_timeout(base: str, count: int) -> bool:
    results = fire(base, SAMPLE_LONG, count)
    statuses = Counter(item["status"] for item in results)
    accepted = [item for item in results if item["status"] == 200]
    rejected = [item for item in results if item["status"] == 429]

    print(f"状态分布：{dict(statuses)}")
    checks = {
        "仅 1 个成功（无重复处理）": len(accepted) == 1,
        "其余全部 429": len(rejected) == count - 1,
        "Retry-After 均为 5": all(
            item["retry_after"] == EXPECTED_RETRY_AFTER for item in rejected
        ),
        "成功响应为完整 WAV": all(item["riff"] for item in accepted),
    }
    if rejected:
        print("429 错误体样例：", rejected[0].get("body", ""))
    return report(checks)


def report(checks: dict) -> bool:
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    return all(checks.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Ming-3.0-tts 并发与队列验收")
    parser.add_argument("--base", default="http://127.0.0.1:8768")
    parser.add_argument("--phase", choices=("capacity", "timeout"), required=True)
    args = parser.parse_args()

    if args.phase == "capacity":
        ok = phase_capacity(args.base, 20)
    else:
        ok = phase_timeout(args.base, 9)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
