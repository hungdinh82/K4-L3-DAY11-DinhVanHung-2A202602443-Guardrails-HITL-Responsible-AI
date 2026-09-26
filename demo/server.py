"""Serve the dashboard and expose a small, guarded Blue Agent chat API."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import unicodedata
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agents.agent import create_blue_agent  # noqa: E402
from core.config import blue_provider_label, get_openrouter_api_key  # noqa: E402
from core.utils import chat_with_agent  # noqa: E402
from guardrails.input_guardrails import (  # noqa: E402
    InputGuardrailPlugin,
    detect_injection,
    topic_filter,
)
from guardrails.output_guardrails import OutputGuardrailPlugin  # noqa: E402

MAX_MESSAGE_LENGTH = 8_000
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 60

_agent = None
_runner = None
_agent_lock = threading.Lock()
_chat_lock = threading.Lock()
_rate_lock = threading.Lock()
_request_times: dict[str, deque[float]] = defaultdict(deque)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def classify_message(message: str) -> dict | None:
    """Return a terminal guardrail response, or None when Blue may answer."""
    text = (message or "").strip()
    if not text:
        return {
            "outcome": "blocked",
            "title": "BLOCKED · Empty input",
            "detail": "Hãy nhập một câu hỏi ngân hàng cụ thể.",
            "response_label": "Phản hồi hệ thống",
            "response": "Tôi chưa nhận được nội dung cần hỗ trợ.",
            "trace": ["Rate limiter", "Input guardrail · STOP"],
        }

    if detect_injection(text) == "BLOCK":
        return {
            "outcome": "blocked",
            "title": "BLOCKED · Prompt injection detected",
            "detail": "Yêu cầu bị dừng trước Blue Agent để bảo vệ chỉ dẫn và dữ liệu nội bộ.",
            "response_label": "Phản hồi an toàn",
            "response": (
                "Tôi không thể cung cấp thông tin xác thực, chỉ dẫn hệ thống hoặc "
                "dữ liệu nội bộ. Tôi có thể hỗ trợ bạn về dịch vụ ngân hàng VinBank."
            ),
            "trace": ["Rate limiter", "Input guardrail · STOP"],
        }

    if topic_filter(text) == "BLOCK":
        return {
            "outcome": "blocked",
            "title": "BLOCKED · Outside VinBank scope",
            "detail": "Blue Agent chỉ xử lý các câu hỏi ngân hàng hợp lệ.",
            "response_label": "Phản hồi an toàn",
            "response": (
                "Tôi chỉ có thể hỗ trợ các chủ đề ngân hàng như tài khoản, tiết kiệm, "
                "khoản vay, thẻ và giao dịch VinBank."
            ),
            "trace": ["Rate limiter", "Input guardrail · STOP"],
        }

    folded = _fold(text)
    if "transfer" in folded or "chuyen tien" in folded:
        return {
            "outcome": "review",
            "title": "HITL REVIEW · High-risk action",
            "detail": "Yêu cầu chuyển tiền cần người có thẩm quyền xác nhận trước khi thực thi.",
            "response_label": "Phản hồi hệ thống",
            "response": (
                "Tôi đã ghi nhận yêu cầu. Vui lòng xác nhận người nhận, số tiền và mục đích; "
                "giao dịch chỉ được tiếp tục sau bước phê duyệt của nhân viên VinBank."
            ),
            "trace": [
                "Rate limiter",
                "Input guardrail",
                "Blue agent · HOLD",
                "HITL review",
            ],
        }
    return None


def _rate_limited(client_id: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        events = _request_times[client_id]
        while events and now - events[0] >= RATE_WINDOW_SECONDS:
            events.popleft()
        if len(events) >= RATE_LIMIT:
            return True
        events.append(now)
        return False


def _get_agent_pair():
    global _agent, _runner
    with _agent_lock:
        if _agent is None or _runner is None:
            plugins = [
                InputGuardrailPlugin(),
                OutputGuardrailPlugin(use_llm_judge=False),
            ]
            _agent, _runner = create_blue_agent(plugins)
    return _agent, _runner


def _run_blue(message: str) -> str:
    agent, runner = _get_agent_pair()
    with _chat_lock:
        response, _ = asyncio.run(chat_with_agent(agent, runner, message))
    return (response or "").strip()


def process_message(message: str, client_id: str) -> tuple[int, dict]:
    """Run the server-side guardrails and invoke Blue only for allowed input."""
    if len(message or "") > MAX_MESSAGE_LENGTH:
        return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {
            "outcome": "error",
            "error": f"Nội dung vượt quá {MAX_MESSAGE_LENGTH} ký tự.",
        }
    if _rate_limited(client_id):
        return HTTPStatus.TOO_MANY_REQUESTS, {
            "outcome": "blocked",
            "title": "BLOCKED · Rate limit exceeded",
            "detail": "Đã vượt quá 5 yêu cầu trong 60 giây.",
            "response_label": "Phản hồi hệ thống",
            "response": "Vui lòng đợi một phút rồi thử lại.",
            "trace": ["Rate limiter · STOP"],
        }

    terminal = classify_message(message)
    if terminal is not None:
        return HTTPStatus.OK, terminal

    if not get_openrouter_api_key():
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "outcome": "error",
            "error": "Thiếu OPENROUTER_API_KEY trong file .env; Blue Agent chưa thể trả lời.",
        }

    try:
        response = _run_blue(message)
    except Exception as exc:  # Keep provider details and credentials out of logs.
        print(
            f"Blue Agent error: {type(exc).__name__} "
            f"(status={getattr(exc, 'status_code', 'unknown')})",
            file=sys.stderr,
        )
        return HTTPStatus.BAD_GATEWAY, {
            "outcome": "error",
            "error": f"Blue Agent tạm thời không phản hồi ({type(exc).__name__}).",
        }

    if not response:
        return HTTPStatus.BAD_GATEWAY, {
            "outcome": "error",
            "error": "Blue Agent trả về phản hồi rỗng.",
        }

    return HTTPStatus.OK, {
        "outcome": "allowed",
        "title": "ALLOWED · Blue Agent response",
        "detail": "Input hợp lệ và phản hồi đã đi qua Output Guardrail.",
        "response_label": f"Blue Agent · {blue_provider_label()}",
        "response": response,
        "trace": [
            "Rate limiter",
            "Input guardrail",
            "Blue agent",
            "Output guardrail",
            "Audit + egress",
        ],
    }


class DemoHandler(SimpleHTTPRequestHandler):
    """Static-file handler with JSON endpoints for the live demo."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/demo/")
            self.end_headers()
            return
        if path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "model": blue_provider_label(),
                    "api_key_configured": bool(get_openrouter_api_key()),
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/chat":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64_000:
                self._send_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"outcome": "error", "error": "Request body quá lớn."},
                )
                return
            payload = json.loads(self.rfile.read(length) or b"{}")
            message = payload.get("message", "")
            if not isinstance(message, str):
                raise ValueError("message must be a string")
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"outcome": "error", "error": f"JSON không hợp lệ: {exc}"},
            )
            return

        client_id = self.client_address[0] if self.client_address else "local"
        status, result = process_message(message, client_id)
        self._send_json(status, result)


def main() -> None:
    host = os.environ.get("DEMO_HOST", "127.0.0.1")
    port = int(os.environ.get("DEMO_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"VinBank live demo: http://{host}:{port}/demo/")
    print(f"Blue Agent: {blue_provider_label()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
