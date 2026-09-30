"""Tự kiểm tra thiết bị và chọn cấu hình chạy phù hợp cho từng máy (mạnh / yếu / không có GPU).

Chạy thử model tách nền THẬT trên GPU (bắt các lỗi "có GPU nhưng không chạy được": card quá cũ,
thiếu VRAM, driver lỗi) và đo tốc độ CPU, rồi lưu cấu hình vào .cache/device.json:

  {"rvm_device": "cuda|cpu", "matte_width": 1080|720|540, "whisper_device": "cuda|cpu", ...}

  python device.py            # kiểm tra + lưu cấu hình (Setup.bat gọi)
  set VHM_FORCE_CPU=1         # ép chạy toàn bộ bằng CPU (khi GPU có vấn đề)
  set VHM_CPU_THREADS=4       # giới hạn số luồng CPU
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

APP = Path(__file__).resolve().parent
PROFILE = APP / ".cache" / "device.json"
RVM_MODEL = APP / "models" / "rvm_mobilenetv3_fp32.torchscript"
MIN_CC = (5, 0)  # torch bản CUDA 12 không còn chạy trên card cũ hơn (Kepler)
VRAM_FULL_GB = 3.5  # đủ cho tách nền 1080 + Whisper cùng lúc trên GPU
VRAM_MIN_GB = 1.8  # dưới mức này dùng CPU cho chắc


def force_cpu() -> bool:
    return os.environ.get("VHM_FORCE_CPU", "").strip() not in ("", "0")


def cpu_threads() -> int:
    """Số luồng CPU cho tách nền; VHM_CPU_THREADS=4 để giới hạn (máy vẫn mượt cho việc khác)."""
    try:
        return max(1, int(os.environ.get("VHM_CPU_THREADS", "")))
    except ValueError:
        return os.cpu_count() or 1


def _bench(model, device: str, width: int, frames: int) -> float:
    """Frame/giây của model tách nền ở chiều rộng width (khung dọc 9:16)."""
    import torch

    h = round(width * 16 / 9) // 2 * 2
    x = torch.rand(1, 3, h, width, device=device)
    rec = [None] * 4
    ratio = min(1.0, 512 / h)
    with torch.no_grad():
        for _ in range(2):  # khởi động
            _f, _p, *rec = model(x, *rec, ratio)
        if device == "cuda":
            torch.cuda.synchronize()
        t = time.time()
        for _ in range(frames):
            _f, pha, *rec = model(x, *rec, ratio)
        pha.cpu()
    return frames / max(1e-6, time.time() - t)


def detect(log=print) -> dict:
    """Kiểm tra thật và trả về cấu hình. Không bao giờ ném lỗi: có vấn đề thì lùi về CPU."""
    import torch

    warnings.filterwarnings("ignore", category=FutureWarning)
    prof = {"gpu_name": None, "vram_gb": 0.0, "rvm_device": "cpu", "matte_width": 720,
            "whisper_device": "cpu", "reason": "", "cpu_fps": None, "gpu_fps": None,
            "cpu_threads": cpu_threads()}
    notes = []

    # --- GPU ---
    if force_cpu():
        notes.append("VHM_FORCE_CPU=1: ép dùng CPU")
    elif not torch.cuda.is_available():
        notes.append("không có GPU NVIDIA dùng được (hoặc torch bản CPU)")
    else:
        try:
            props = torch.cuda.get_device_properties(0)
            prof["gpu_name"] = props.name
            prof["vram_gb"] = round(props.total_memory / 1024 ** 3, 1)
            cc = (props.major, props.minor)
            if cc < MIN_CC:
                notes.append(f"card {props.name} đời quá cũ (compute {cc[0]}.{cc[1]})")
            elif prof["vram_gb"] < VRAM_MIN_GB:
                notes.append(f"card {props.name} ít VRAM ({prof['vram_gb']} GB)")
            else:
                model = torch.jit.load(str(RVM_MODEL), map_location="cuda").eval()
                width = 1080 if prof["vram_gb"] >= VRAM_FULL_GB else 720
                fps = _bench(model, "cuda", width, 6)  # chạy thật: bắt lỗi kernel / thiếu VRAM
                prof.update(rvm_device="cuda", matte_width=width, gpu_fps=round(fps, 1))
                # Whisper chạy tiến trình riêng, cùng lúc với tách nền -> cần đủ VRAM cho cả hai
                prof["whisper_device"] = "cuda" if prof["vram_gb"] >= VRAM_FULL_GB else "cpu"
                del model
                torch.cuda.empty_cache()
        except Exception as e:  # "no kernel image", out of memory, driver lỗi...
            msg = str(e).strip().splitlines()[0][:160] if str(e).strip() else type(e).__name__
            notes.append(f"GPU chạy thử lỗi: {msg}")
            prof.update(rvm_device="cpu", whisper_device="cpu", gpu_fps=None)

    # --- CPU: đo sức máy để chọn độ phân giải tách nền khi phải chạy bằng CPU ---
    if prof["rvm_device"] == "cpu":
        try:
            torch.set_num_threads(prof["cpu_threads"])
            model = torch.jit.load(str(RVM_MODEL), map_location="cpu").eval()
            fps = _bench(model, "cpu", 540, 2)
            prof["cpu_fps"] = round(fps, 2)
            # máy mạnh: 720 cho viền tóc đẹp hơn; máy yếu: 540 cho đỡ lâu
            prof["matte_width"] = 720 if fps >= 3.0 else 540
            notes.append(f"CPU {prof['cpu_threads']} luồng, tách nền ~{fps:.1f} frame/giây ở 540px")
        except Exception as e:
            notes.append(f"CPU chạy thử lỗi: {e}")

    prof["reason"] = "; ".join(notes)
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
    return prof


def load() -> dict | None:
    """Cấu hình đã lưu (Setup.bat tạo). VHM_FORCE_CPU luôn được ưu tiên."""
    try:
        prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if force_cpu():
        prof.update(rvm_device="cpu", whisper_device="cpu", matte_width=min(prof.get("matte_width", 720), 720))
    return prof


def describe(prof: dict) -> str:
    if prof["rvm_device"] == "cuda":
        s = f"GPU {prof['gpu_name']} ({prof['vram_gb']} GB): tách nền {prof['matte_width']}px"
        s += f", Whisper trên {'GPU' if prof['whisper_device'] == 'cuda' else 'CPU'}"
    else:
        s = f"CPU: tách nền {prof['matte_width']}px, Whisper trên CPU (chậm hơn GPU nhưng vẫn chạy)"
    return s + (f"  [{prof['reason']}]" if prof.get("reason") else "")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = detect()
    print("Cấu hình máy:", describe(p))
