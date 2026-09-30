"""Đo tốc độ nói (chữ/giây) của từng clip bằng Whisper 'small'.

Chạy trong tiến trình RIÊNG (hook_merge.py gọi): thư viện CUDA của Whisper (ctranslate2) và của
torch (tách nền) xung đột nếu nạp chung một tiến trình.

  stdin : JSON [{"path": "...", "segments": [[start, end], ...]}, ...]
  stdout: dòng cuối là JSON [rate | null, ...]
  python speech_rate.py --device cuda|cpu
  python speech_rate.py --download     # chỉ tải model (Setup.bat dùng)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

WHISPER_DIR = Path(__file__).resolve().parent / ".cache" / "whisper-small"  # không đóng vào ZIP


def ensure_model() -> None:
    if (WHISPER_DIR / "model.bin").exists():
        return
    from faster_whisper.utils import download_model

    print("Tải model Whisper small (~480 MB, chỉ 1 lần) ...", file=sys.stderr, flush=True)
    download_model("small", output_dir=str(WHISPER_DIR))


def load_model(device: str):
    from faster_whisper import WhisperModel

    if device == "cuda":  # dùng chung thư viện CUDA đi kèm torch
        import torch

        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(lib)
        os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")
        return WhisperModel(str(WHISPER_DIR), device="cuda", compute_type="int8_float32")
    return WhisperModel(str(WHISPER_DIR), device="cpu", compute_type="int8")


def load_audio(path: str) -> np.ndarray:
    """Tự đọc audio bằng ffmpeg (mono 16 kHz) thay vì để faster-whisper dùng PyAV:
    PyAV bản mới (>= 19) không còn tương thích với faster-whisper."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def rate(model, path: str, segments: list) -> float | None:
    """Tiếng Việt mỗi chữ là 1 âm tiết: số chữ Whisper nhận ra trong phần giữ lại / thời gian nói.
    Đếm chữ nên không bị nhạc nền đánh lừa như cách đếm đỉnh âm lượng."""
    ws, _ = model.transcribe(load_audio(path), language="vi", word_timestamps=True, vad_filter=False)
    words = [w for s in ws for w in s.words]
    talk = sum(b - a for a, b in segments)
    n = sum(1 for w in words if any(a <= (w.start + w.end) / 2 <= b for a, b in segments))
    return n / talk if n >= 8 and talk >= 1.5 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cpu")
    ap.add_argument("--download", action="store_true", help="Chỉ tải model rồi thoát")
    args = ap.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ensure_model()
    if args.download:
        return 0
    jobs = json.loads(sys.stdin.read())
    model = load_model(args.device)
    print(json.dumps([rate(model, j["path"], j["segments"]) for j in jobs]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
