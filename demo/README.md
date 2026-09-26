# VinBank Guardrail Command Center

Giao diện demo tĩnh cho lab Guardrails / HITL. Dashboard đọc các bằng chứng
thật từ `outputs/` và có Security Playground để giải thích pipeline trực tiếp
khi thuyết trình. Playground là mô phỏng policy tại browser: không gọi model,
không lưu prompt, và không thay thế các guardrail Python được chấm.

Từ thư mục gốc repo, chạy:

```bash
python3 -m http.server 8080
```

Sau đó mở [http://localhost:8080/demo/](http://localhost:8080/demo/).

Để cập nhật dashboard bằng dữ liệu mới, chạy `python src/main.py --part 3`
rồi nhấn **Tải lại artifacts** trong giao diện.
