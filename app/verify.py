"""Kiểm tra Video Hook Merger đã sẵn sàng chạy.

  python verify.py            # kiểm tra file, thư viện, ffmpeg, font tiếng Việt, model
  python verify.py --smoke    # thêm: tự tạo 3 clip thử và chạy toàn bộ quy trình ghép
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAIL = []


def check(ok: bool, label: str, hint: str = "") -> None:
    print(("  [OK]   " if ok else "  [LỖI]  ") + label + ("" if ok else f"\n         -> {hint}"), flush=True)
    if not ok:
        FAIL.append(label)


def verify_manifest() -> None:
    manifest = ROOT / "MANIFEST.sha256"
    if not manifest.exists():
        print("  [--]   Không có MANIFEST.sha256 (bản đang phát triển), bỏ qua kiểm tra checksum")
        return
    bad = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        f = ROOT / rel
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            bad.append(rel)
    check(not bad, "Toàn vẹn file (MANIFEST.sha256)", f"File bị thiếu/hỏng: {', '.join(bad[:5])}. Giải nén lại bản ZIP.")


def verify_imports() -> None:
    for mod, pipname in (("PIL", "pillow"), ("numpy", "numpy"), ("fontTools", "fonttools"),
                         ("faster_whisper", "faster-whisper"), ("customtkinter", "customtkinter"),
                         ("torch", "torch")):
        if mod == "faster_whisper":
            # kiểm tra ở tiến trình riêng: nạp chung với torch GPU trong 1 tiến trình làm xung đột cuDNN
            # (app cũng luôn chạy Whisper ở tiến trình riêng)
            ok = subprocess.run([sys.executable, "-c", "import faster_whisper"], capture_output=True).returncode == 0
        else:
            try:
                __import__(mod)
                ok = True
            except Exception:
                ok = False
        check(ok, f"Thư viện {pipname}", "Chạy lại Setup.bat (hoặc install.sh)")
    try:
        import tkinter  # noqa: F401
        ok = True
    except Exception:
        ok = False
    check(ok, "Thư viện giao diện tkinter", "Cài lại Python từ python.org, giữ tuỳ chọn 'tcl/tk and IDLE'")
    try:
        import torch
        dev = "GPU " + torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU (chạy chậm hơn GPU)"
        print(f"  [--]   torch {torch.__version__} sẽ chạy trên {dev}")
    except Exception:
        pass


def verify_ffmpeg() -> None:
    for exe in ("ffmpeg", "ffprobe"):
        check(bool(shutil.which(exe)), f"{exe} trong PATH", "Windows: `winget install Gyan.FFmpeg` rồi mở lại cửa sổ")
    if shutil.which("ffmpeg"):
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        flt = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        for codec in ("libx264", "ffv1", "aac"):
            check(codec in enc, f"ffmpeg encoder {codec}", "Cài bản ffmpeg đầy đủ (full build)")
        for name in ("atempo", "alphamerge", "tpad", "areverse", "overlay"):
            check(f" {name} " in flt, f"ffmpeg filter {name}", "Cài bản ffmpeg mới hơn (>= 5.0)")


def verify_assets() -> None:
    sys.path.insert(0, str(ROOT))
    import design as dz

    check((ROOT / "models" / "rvm_mobilenetv3_fp32.torchscript").exists(), "Model tách nền (RVM)",
          "Thiếu models/rvm_mobilenetv3_fp32.torchscript, giải nén lại bản ZIP")
    check((ROOT / ".cache" / "whisper-small" / "model.bin").exists(), "Model Whisper small (đồng bộ tốc độ nói)",
          "Chạy lại Setup.bat để tải model (~480 MB)")
    base = "aăâeêioôơuưy"
    tones = ["", "̀", "́", "̉", "̃", "̣"]
    vi = {unicodedata.normalize("NFC", b + t) for b in base for t in tones} | {"đ"}
    vi |= {c.upper() for c in vi}
    specs = {s.file: s for p in dz.PRESETS.values() for s in (p.line1, p.line2)}
    for name, spec in sorted(specs.items()):
        try:
            miss = [c for c in vi if ord(c) not in dz.cmap_of(spec)]
        except Exception as e:  # font thiếu / hỏng
            miss = [str(e)]
        check(not miss, f"Font {name}: đủ 146 ký tự tiếng Việt", f"Thiếu: {''.join(miss)[:40]}")


def smoke() -> None:
    """Tạo 3 clip thử (hình màu + tiếng bíp có khoảng lặng) và ghép thật."""
    with tempfile.TemporaryDirectory(prefix="hook-merge-smoke-") as tmp:
        tmp = Path(tmp)
        clips = tmp / "clips"
        clips.mkdir()
        for i, color in enumerate(("0xE8DED3", "0xD9CFC4", "0xEDE5DA"), 1):
            subprocess.run(["ffmpeg", "-v", "error", "-y",
                            "-f", "lavfi", "-i", f"color=c={color}:s=360x640:r=24:d=3",
                            "-f", "lavfi", "-i", "sine=f=440:d=3",
                            "-af", "volume=enable='lt(t,0.6)+between(t,1.4,2.0)':volume=0",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(clips / f"{i}.mp4")], check=True)
        (clips / "b1 Đi tiệc mà chưa biết mặc gì thì xem mẫu này nha").write_bytes(b"")
        # Whisper (đồng bộ tốc độ nói) phải chạy được thật, không chỉ cài được: đọc audio + nhận dạng
        job = '[{"path": "%s", "segments": [[0, 3]]}]' % (clips / "1.mp4").as_posix()
        res = subprocess.run([sys.executable, str(ROOT / "speech_rate.py"), "--device", "cpu"], input=job,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(res.returncode == 0 and res.stdout.strip().startswith("["),
              "Chạy thử Whisper (đo tốc độ nói)", (res.stderr.strip().splitlines() or ["?"])[-1][:300])
        out = tmp / "out.mp4"
        res = subprocess.run([sys.executable, str(ROOT / "hook_merge.py"), str(clips), "-o", str(out),
                              "--hook", "Đi tiệc mà chưa biết mặc gì|thì xem *mẫu này* nha"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok = res.returncode == 0 and out.exists()
        check(ok, "Chạy thử ghép 3 clip (cắt lặng + tăng tốc + chữ + tách nền)",
              (res.stderr or res.stdout)[-800:])
        if ok:
            dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(out)], capture_output=True, text=True).stdout.strip()
            print(f"  [--]   Video thử dài {float(dur):.2f}s (3 clip x 3s, đã cắt lặng + tăng tốc)")


def verify_device() -> None:
    """Chạy thử model thật trên GPU/CPU; GPU hỏng không phải lỗi: tool tự dùng CPU."""
    import device

    try:
        prof = device.detect()
        print("  [--]   Thiết bị: " + device.describe(prof))
        ok = True
    except Exception as e:
        ok = False
        print(f"         {e}")
    check(ok, "Kiểm tra thiết bị (GPU/CPU chạy được model tách nền)", "Xem lỗi ở trên")


def smoke_gui() -> None:
    """Mở rồi đóng cửa sổ giao diện để chắc chắn gui.py chạy được."""
    try:
        import gui

        app = gui.App([])
        app.update()
        app.destroy()
        ok, msg = True, ""
    except Exception as e:  # không có màn hình / thiếu tkinter
        ok, msg = False, str(e)
    check(ok, "Mở thử giao diện (gui.py)", msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="Chạy thử toàn bộ quy trình với clip giả")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    print("== Video Hook Merger: kiểm tra ==")
    verify_manifest()
    verify_ffmpeg()
    verify_imports()
    if not FAIL:
        verify_assets()
    if not FAIL:
        verify_device()
    if args.smoke and not FAIL:
        smoke()
        smoke_gui()
    print("\nKẾT QUẢ: " + ("SẴN SÀNG. Mở giao diện bằng shortcut Desktop hoặc Video Hook Merger.bat." if not FAIL
                          else f"CÒN {len(FAIL)} LỖI, xem các dòng [LỖI] ở trên."))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
