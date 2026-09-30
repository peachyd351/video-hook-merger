"""Cài Video Hook Merger vào môi trường Python riêng (.venv) trong thư mục tool.

- Không cài phần mềm hệ thống. Thiếu ffmpeg hoặc Python thì chỉ báo rõ cách cài.
- Hỏi xác nhận trước khi tải thư viện (Pillow, numpy, fontTools, torch) từ Internet.
- Chạy lại bao nhiêu lần cũng được: chỉ cài tiếp phần còn thiếu (ví dụ sau khi mất mạng / đổi IP
  giữa chừng). .venv hỏng dở thì tự tạo lại; muốn xoá sạch cài lại từ đầu thì dùng --reinstall.

  python install.py                 # cài, tự chọn torch GPU (NVIDIA) hoặc CPU
  python install.py --torch cpu     # ép bản CPU (nhẹ hơn, chạy chậm hơn)
  python install.py --no-venv       # dùng Python hiện tại, chỉ kiểm tra (không tải gì)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu126",  # còn hỗ trợ GPU đời GTX 10xx
    "cpu": "https://download.pytorch.org/whl/cpu",
}


def say(msg: str) -> None:
    print(msg, flush=True)


def venv_python() -> Path:
    win = VENV / "Scripts" / "python.exe"
    return win if win.exists() else VENV / "bin" / "python"


def check_host() -> list[str]:
    problems = []
    if sys.version_info < (3, 9):
        problems.append(f"Cần Python >= 3.9 (đang có {sys.version.split()[0]}). Tải tại https://www.python.org/downloads/")
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            problems.append(f"Không tìm thấy {exe} trong PATH. Windows: mở PowerShell chạy "
                            "`winget install Gyan.FFmpeg`, rồi mở lại cửa sổ. macOS: `brew install ffmpeg`.")
    if shutil.which("ffmpeg"):
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        for codec in ("libx264", "ffv1", "aac"):
            if codec not in enc:
                problems.append(f"Bản ffmpeg hiện tại thiếu encoder {codec}; hãy cài bản ffmpeg đầy đủ (full build).")
    return problems


def pick_torch(choice: str) -> str:
    if choice != "auto":
        return choice
    return "cuda" if shutil.which("nvidia-smi") else "cpu"


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [y/N]: ").strip().lower() in {"y", "yes", "c", "co", "có"}
    except EOFError:
        return False


BASIC_MODULES = ["PIL", "numpy", "fontTools", "faster_whisper", "customtkinter"]
WHISPER_MODEL = ROOT / ".cache" / "whisper-small" / "model.bin"  # dùng để đồng bộ tốc độ nói
NET_HINT = ("Tải bị gián đoạn (mất mạng / đổi IP / mạng chập chờn?). Kiểm tra mạng rồi chạy lại "
            "Setup.bat: tool sẽ cài TIẾP phần còn thiếu, file đã tải xong không phải tải lại.")


def pip(py: Path, *args: str) -> None:
    # --retries/--timeout: chịu được mạng chập chờn; file tải xong được pip giữ trong cache.
    subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                    "--retries", "10", "--timeout", "60", *args], check=True)


def can_import(py: Path, *modules: str) -> bool:
    if not py.exists():
        return False
    code = "import " + ", ".join(modules) if modules else "pass"
    return subprocess.run([str(py), "-c", code], capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cài Video Hook Merger")
    ap.add_argument("--torch", choices=["auto", "cuda", "cpu", "skip"], default="auto",
                    help="auto: có card NVIDIA thì dùng bản GPU, không thì CPU")
    ap.add_argument("--yes", action="store_true", help="Đồng ý tải thư viện, không hỏi lại")
    ap.add_argument("--no-venv", action="store_true",
                    help="Không tạo .venv, không tải gì: dùng Python hiện tại (đã có sẵn thư viện)")
    ap.add_argument("--reinstall", action="store_true", help="Xoá .venv cũ của tool rồi cài lại")
    ap.add_argument("--skip-verify", action="store_true", help="Không chạy verify.py sau khi cài (Setup.bat tự chạy)")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    say("== Video Hook Merger: cài đặt ==")
    problems = check_host()
    if problems:
        say("Chưa cài được vì máy còn thiếu:")
        for p in problems:
            say(f"  - {p}")
        return 2
    say("Python + ffmpeg: OK")

    if args.no_venv:
        say("Chế độ --no-venv: dùng Python hiện tại, không tải thư viện.")
        py = Path(sys.executable)
    else:
        if VENV.exists() and (args.reinstall or not can_import(venv_python())):
            say("Xoá .venv cũ (cài lại từ đầu)." if args.reinstall else "Môi trường .venv bị hỏng dở, tạo lại.")
            shutil.rmtree(VENV)
        torch_kind = pick_torch(args.torch)
        py = venv_python()
        need_venv = not py.exists()
        need_basic = need_venv or not can_import(py, *BASIC_MODULES)
        need_torch = torch_kind != "skip" and (need_venv or not can_import(py, "torch"))
        need_whisper = not WHISPER_MODEL.exists()
        if not (need_basic or need_torch or need_whisper):
            say("Thư viện Python + model Whisper đã đủ, không cần tải thêm.")
        else:
            parts = []
            if need_basic:
                parts.append("thư viện cơ bản ~200 MB")
            if need_torch:
                parts.append(f"torch bản {torch_kind.upper()} " + ("~2.5 GB" if torch_kind == "cuda" else "~250 MB"))
            if need_whisper:
                parts.append("model Whisper small ~480 MB")
            what = ", ".join(parts)
            if not confirm(f"Sẽ tải {what} từ Internet vào thư mục {VENV}. Tiếp tục?", args.yes):
                say("Đã huỷ, chưa tải gì.")
                return 1
            try:
                if need_venv:
                    say("Tạo môi trường .venv ...")
                    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
                    py = venv_python()  # tính lại sau khi tạo (Windows: Scripts\python.exe)
                    pip(py, "--upgrade", "pip")
                if need_basic:
                    pip(py, "-r", str(ROOT / "requirements.txt"))
                if need_torch:
                    say(f"Tải torch bản {torch_kind.upper()} ...")
                    pip(py, "torch", "--index-url", TORCH_INDEX[torch_kind])
                if need_whisper:
                    say("Tải model Whisper small (đo tốc độ nói để đồng bộ 3 clip) ...")
                    subprocess.run([str(py), str(ROOT / "speech_rate.py"), "--download"], check=True)
            except subprocess.CalledProcessError:
                say("")
                say(NET_HINT)
                if torch_kind == "cuda" and need_torch:
                    say("Nếu lỗi lặp lại dù mạng ổn định: chạy `Setup.bat -Torch cpu` để dùng bản CPU.")
                return 3

    if args.skip_verify:
        say("Cài thư viện xong.")
        return 0
    say("Kiểm tra sau khi cài ...")
    return subprocess.run([str(py), str(ROOT / "verify.py")]).returncode


if __name__ == "__main__":
    sys.exit(main())
