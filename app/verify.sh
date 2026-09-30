#!/usr/bin/env sh
# Kiểm tra Video Hook Merger (thêm --smoke để chạy thử toàn bộ quy trình).
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY="$(command -v python3 || command -v python)"; fi
export PYTHONIOENCODING=utf-8
exec "$PY" "$ROOT/verify.py" "$@"
