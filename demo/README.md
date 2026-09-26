# VinBank Guardrail Command Center

Giao diện demo trực tiếp cho lab Guardrails / HITL. Dashboard đọc bằng chứng
từ `outputs/`; Security Playground gửi prompt qua Input Guardrail, Blue Agent
OpenRouter và Output Guardrail trước khi hiển thị phản hồi.

Từ thư mục gốc repo, chạy:

```bash
.venv/bin/python demo/server.py
```

Sau đó mở [http://localhost:8080/demo/](http://localhost:8080/demo/).

Blue Agent cần `OPENROUTER_API_KEY` trong file `.env`. Không dùng
`python3 -m http.server`: server tĩnh đó không có endpoint `/api/chat`, nên chỉ
hiển thị được dashboard mà không thể trả lời câu hỏi.

Để cập nhật dashboard bằng dữ liệu mới, chạy `python src/main.py --part 3`
rồi nhấn **Tải lại artifacts** trong giao diện.
