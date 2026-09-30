#!/usr/bin/env sh
# Cài Video Hook Merger (macOS/Linux/Git Bash). Mọi tuỳ chọn chuyển tiếp cho install.py.
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Không tìm thấy Python 3. Tải tại https://www.python.org/downloads/" >&2
  exit 2
fi
export PYTHONIOENCODING=utf-8
exec "$PY" "$ROOT/install.py" "$@"
