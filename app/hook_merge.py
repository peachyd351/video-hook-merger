"""Ghép nhiều clip thành 1 video dọc và chèn hook text 2 dòng ở đầu video.

Kiểu text (theo mẫu "Nàng mặc đẹp"):
  dòng 1: sans nghiêng mảnh (Be Vietnam Pro Light Italic)
  dòng 2: serif đậm (Playfair Display Bold)
  căn giữa khoảng trống từ vạch an toàn Reels (8% trên) tới đỉnh đầu người mẫu, hiện suốt cảnh đầu (clip 1).
Xếp lớp: video gốc (dưới) -> text (giữa) -> người đã tách nền (trên), nên khi
người mẫu tiến lên, đầu sẽ đè lên chữ. Tách nền bằng Robust Video Matting.

Dùng:
  python hook_merge.py <thư_mục_clip | clip1 clip2 ...> [-o out.mp4] [--hook "Dòng 1 | Dòng 2"]

Nguồn text (ưu tiên từ trên xuống):
  1. --hook "Dòng 1 | Dòng 2"
  2. file hook.txt trong thư mục clip (dòng 1 / dòng 2, hoặc 1 câu có dấu |)
  3. tự tạo: chọn ngẫu nhiên từ hooks.txt, tránh lặp lại các hook đã dùng gần đây
Một câu hook không có dấu | sẽ được tự tách thành 2 dòng.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import threading
import warnings

import numpy as np

from PIL import Image, ImageDraw, ImageFont

import design as dz
import device as devmod

HERE = Path(__file__).resolve().parent
HOOK_BANK = HERE / "hooks.txt"
HISTORY = HERE / ".hook_history.json"
RVM_MODEL = HERE / "models" / "rvm_mobilenetv3_fp32.torchscript"
RVM_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.torchscript"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}

MAX_TEXT_W = 0.88
OCCLUDE_MAX = 0.04  # frame đầu (thumbnail): người che > 4% chữ thì đưa chữ lên trước người mẫu
LINE_GAP = 1.28  # khoảng cách tâm 2 dòng / cỡ chữ trung bình (đo từ video mẫu, >= 1.25)

# Cắt phần thừa: ngưỡng im lặng (tương đối theo từng clip) và khoảng đệm quanh lời nói (giây).
SPEECH_DROP = 20  # dB thấp hơn mức giọng nói (phân vị 90)
FLOOR_MARGIN = 6  # dB cao hơn tiếng nền (phân vị 10)
PAD_HEAD = 0.12  # giữ trước câu đầu
PAD_TAIL = 0.30  # giữ sau câu cuối
MAX_PAUSE = 0.45  # khoảng ngừng giữa câu dài hơn mức này thì cắt (jump cut)
GAP_AFTER = 0.12  # giữ sau câu trước
GAP_BEFORE = 0.08  # giữ trước câu sau
MIN_SEGMENT = 0.25  # đoạn giữ lại ngắn hơn mức này thì gộp/bỏ
SYNC_MAX = 0.12  # đồng bộ tốc độ nói: mỗi clip lệch tối đa ±12% so với --speed
SYNC_DEADBAND = 0.03  # chênh < 3% so với chuẩn thì không chỉnh

# Chia dòng hook: câu ngắn thì 1 dòng; dài thì tìm chỗ cắt cân đối + tự nhiên.
SINGLE_LINE_WORDS = 5
SINGLE_LINE_CHARS = 22
SPLIT_STRONG = {"thì", "cứ", "là", "nhưng", "vì", "nên", "mà", "hãy", "chỉ"}  # dòng 2 hay mở bằng các từ này
SPLIT_WEAK = {"mặc", "diện", "chọn", "phối", "ai", "ảnh", "để", "sẽ", "được", "khiến", "giúp", "dừng"}
GLUE_NEXT = {"mọi", "những", "các", "một", "của", "cho", "với", "và", "rất", "cực", "siêu", "quá", "đang",
             "bộ", "chiếc", "cái", "set", "mẫu", "kiểu", "màu", "đi", "đồ", "nàng"}  # không đứng cuối dòng 1
GLUE_PREV = {"này", "đó", "kia", "nha", "nhé", "luôn", "ạ", "thôi", "đâu", "không", "chưa"}  # không mở dòng 2
PARTICLES = {"nha", "nhé", "luôn", "ạ", "thôi", "nhen", "nè", "đó", "ha"}
# Từ ghép hay gặp trong hook thời trang: không cắt dòng ở giữa (không có bộ tách từ tiếng Việt).
COMPOUNDS = {
    "ánh nhìn", "góc nhìn", "tự tin", "dừng lại", "bao giờ", "hết thời", "buổi tiệc", "tối nay", "đi tiệc",
    "điệu đà", "cuối tuần", "hẹn hò", "phối đồ", "set đồ", "mùa đông", "mùa hè", "mùa thu", "gái hàn", "tiểu thư",
    "nổi bật", "sang trọng", "sang chảnh", "thanh lịch", "nữ tính", "cá tính", "dễ thương", "công sở", "bạn thân",
    "đám cưới", "xinh đẹp", "mặc đẹp", "tôn dáng", "hack dáng", "chân váy", "sơ mi", "vài giây", "mọi người",
    "thế nào", "bao nhiêu", "như thế", "đến thế", "đi làm", "đi chơi", "đi học", "nguyên set", "cả ngày",
    "hôm nay", "ngày mai", "trẻ trung", "năng động", "quý phái", "dịu dàng", "ngọt ngào", "cuốn hút", "thu hút",
    "không biết", "chưa biết", "mặc gì", "đẹp nhất", "xinh nhất", "cực kỳ", "siêu xinh", "vừa xinh", "lên đồ",
}
# Từ khoá thời trang được ưu tiên tô màu nhấn (nếu câu không có cụm Viết Hoa / *đánh dấu*).
ACCENT_KEYS = ["vibe gái hàn", "gái hàn", "vibe", "tiểu thư", "sang chảnh", "sang trọng", "thanh lịch", "nữ tính",
               "cá tính", "dễ thương", "nổi bật", "tự tin", "tôn dáng", "hack dáng", "đi tiệc", "hẹn hò", "công sở",
               "đi làm", "đi chơi", "mùa đông", "mùa hè", "set đồ", "outfit", "spotlight", "xinh xỉu", "mê",
               "hút mắt", "buổi tiệc", "tiệc", "sang", "xinh", "chuẩn"]


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        sys.exit(f"Lệnh lỗi: {' '.join(cmd[:3])}...\n{res.stderr[-2000:]}")
    return res.stdout


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
               "-of", "json", str(path)])
    data = json.loads(out)
    info = {"duration": float(data["format"].get("duration", 0)), "audio": False}
    for s in data["streams"]:
        if s["codec_type"] == "video" and "width" not in info:
            num, den = s["r_frame_rate"].split("/")
            info.update(width=s["width"], height=s["height"], fps=float(num) / float(den or 1))
        elif s["codec_type"] == "audio":
            info["audio"] = True
    return info


def load_audio(path: Path) -> np.ndarray:
    """Audio mono 16 kHz dạng float32."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def measure_rates(jobs: list[dict]) -> dict:
    """Gọi speech_rate.py trong tiến trình riêng: thử GPU trước, lỗi/sập thì chạy lại bằng CPU."""
    if not jobs:
        return {}
    prof = devmod.load()
    if prof:  # theo cấu hình đã kiểm tra lúc Setup (card ít VRAM -> Whisper chạy CPU cho khỏi tràn)
        devices = ["cuda", "cpu"] if prof.get("whisper_device") == "cuda" else ["cpu"]
    else:
        import shutil as _sh
        devices = ["cuda", "cpu"] if _sh.which("nvidia-smi") and not devmod.force_cpu() else ["cpu"]
    for dev in devices:
        res = subprocess.run([sys.executable, str(HERE / "speech_rate.py"), "--device", dev],
                             input=json.dumps(jobs), capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        lines = res.stdout.strip().splitlines()
        if res.returncode == 0 and lines:
            return dict(zip((j["path"] for j in jobs), json.loads(lines[-1])))
        reason = (res.stderr.strip().splitlines() or ["không rõ"])[-1][:200]
        print(f"  (Whisper {dev.upper()} lỗi: {reason})")
        print("   -> thử CPU" if dev == "cuda" else "   -> bỏ qua đồng bộ tốc độ nói")
    return {}


def sync_speeds(clips: list[Path], infos: list[dict], args) -> None:
    """Gán tốc độ riêng từng clip để nhịp nói 3 clip đều nhau: clip nói chậm tăng tốc thêm,
    clip nói nhanh giảm bớt, quanh mức --speed và lệch tối đa ±SYNC_MAX."""
    for info in infos:
        info["speed"] = args.speed
    if args.no_sync_speed:
        return
    print("  Đo tốc độ nói từng clip (Whisper) ...")
    jobs = [{"path": str(c), "segments": i["segments"]} for c, i in zip(clips, infos)
            if i["audio"] and not args.mute]
    rates_by_path = measure_rates(jobs)
    rates = [rates_by_path.get(str(c)) for c in clips]
    valid = [r for r in rates if r]
    if len(valid) < 2:
        print("  Đồng bộ tốc độ nói: không đủ clip có giọng nói để so, dùng chung tốc độ", args.speed)
        return
    target = float(np.median(valid))
    print(f"  Đồng bộ tốc độ nói (chuẩn {target:.2f} chữ/giây trước khi tăng tốc):")
    for c, info, r in zip(clips, infos, rates):
        if r:
            factor = target / r
            if abs(factor - 1) < SYNC_DEADBAND:
                factor = 1.0  # chênh quá nhỏ, không chỉnh
            factor = min(1 + SYNC_MAX, max(1 - SYNC_MAX, factor))
            info["speed"] = round(min(2.0, max(0.5, args.speed * factor)), 3)
        rate = f"{r:.2f} chữ/giây" if r else "không đo được"
        print(f"    {c.name}: {rate} -> tốc độ {info['speed']}x")


def detect_silences(path: Path, duration: float) -> list[tuple[float, float]]:
    """Dò khoảng lặng theo độ to RMS từng 20ms với ngưỡng tương đối của chính clip đó:
    thấp hơn giọng nói SPEECH_DROP dB và cao hơn tiếng nền FLOOR_MARGIN dB. Nhờ vậy clip
    có nhạc nền / tiếng phòng vẫn tìm được chỗ ngừng nói."""
    x = load_audio(path)
    hop = 320  # 20ms
    n = len(x) // hop
    if n < 10:
        return []
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(rms)
    db = np.convolve(db, np.ones(3) / 3, mode="same")  # làm mượt nhẹ
    thr = max(np.percentile(db, 10) + FLOOR_MARGIN, np.percentile(db, 90) - SPEECH_DROP)
    quiet = db < thr
    out, i, min_len = [], 0, round(0.2 / 0.02)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= min_len:
                s, e = i * 0.02, duration if j >= n else j * 0.02
                if out and s - out[-1][1] < 0.1:  # tiếng động lẻ < 0.1s giữa 2 khoảng lặng -> gộp
                    s = out.pop()[0]
                out.append((s, e))
            i = j
        else:
            i += 1
    return out


def speech_segments(path: Path, duration: float) -> tuple[list[tuple[float, float]], dict]:
    """Chia clip thành các đoạn có lời nói: cắt lặng đầu, lặng cuối và các khoảng ngừng dài
    giữa câu (jump cut). Hình + tiếng cắt cùng mốc nên khẩu hình vẫn khớp."""
    cuts, stats = [], {"head": 0.0, "tail": 0.0, "pauses": 0, "pause_s": 0.0}
    for s, e in detect_silences(path, duration):
        if s <= 0.05:  # lặng ở đầu clip
            cuts.append((0.0, max(0.0, e - PAD_HEAD)))
            stats["head"] = cuts[-1][1]
        elif e >= duration - 0.15:  # lặng kéo tới cuối clip
            cuts.append((min(duration, s + PAD_TAIL), duration))
            stats["tail"] = duration - cuts[-1][0]
        elif e - s > MAX_PAUSE:  # ngừng dài giữa câu
            cuts.append((s + GAP_AFTER, e - GAP_BEFORE))
            stats["pauses"] += 1
            stats["pause_s"] += cuts[-1][1] - cuts[-1][0]
    keep, pos = [], 0.0
    for cs, ce in sorted(cuts):
        if cs - pos >= MIN_SEGMENT:
            keep.append((pos, cs))
        pos = max(pos, ce)
    if duration - pos >= MIN_SEGMENT:
        keep.append((pos, duration))
    if not keep or sum(e - s for s, e in keep) < 1.0:
        return [(0.0, duration)], {"head": 0.0, "tail": 0.0, "pauses": 0, "pause_s": 0.0}
    return keep, stats


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def collect_clips(inputs: list[str]) -> list[Path]:
    clips: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            clips += sorted((f for f in p.iterdir()
                             if f.suffix.lower() in VIDEO_EXT and not f.stem.endswith("_hook")), key=natural_key)
        elif p.is_file():
            clips.append(p)
        else:
            sys.exit(f"Không tìm thấy: {item}")
    if not clips:
        sys.exit("Không có clip video nào để ghép.")
    return clips


# ---------- hook text ----------

def cap(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:]


def split_hook(text: str) -> tuple[str, str]:
    """Chia hook thành (dòng nhỏ, dòng đậm). Câu ngắn -> 1 dòng: ("", câu)."""
    a, b = _split(text)
    if not a:
        return "", cap(b)
    # chỉ viết hoa đầu câu; dòng 2 là nửa sau của câu nên giữ nguyên cách viết (vd "ảnh nào cũng ra…")
    return cap(a.rstrip(" ,:;–—-")), b.lstrip(" ,:;–—-")


def _plain(t: str) -> str:
    return t.replace("*", "")


def _split(text: str) -> tuple[str, str]:
    text = dz.clean_text(text)
    if "|" in text:  # người dùng tự chia
        a, b = text.split("|", 1)
        return a.strip(), b.strip()
    words = text.split()
    if len(words) <= SINGLE_LINE_WORDS or len(_plain(text)) <= SINGLE_LINE_CHARS:
        return "", text  # câu ngắn: 1 dòng đậm
    low = [re.sub(r"[^\w]", "", w.lower()) for w in words]
    total = len(_plain(text))
    in_marker, marked = False, []  # từ nằm trong *...* (không cắt ở giữa)
    for wd in words:
        starts = wd.startswith("*")
        in_marker = in_marker or starts
        marked.append(in_marker)
        if wd.endswith("*") and (len(wd) > 1 or not starts):
            in_marker = False
    best, best_i = None, len(words) // 2
    for i in range(2, len(words) - 1):  # mỗi dòng ít nhất 2 chữ
        la, lb = len(_plain(" ".join(words[:i]))), len(_plain(" ".join(words[i:])))
        score = abs(la - lb) / total  # càng cân càng tốt
        if words[i - 1][-1] in ",.:;!?…":
            score -= 0.25  # cắt ngay sau dấu câu
        if low[i] in SPLIT_STRONG:
            score -= 0.20  # dòng 2 mở bằng từ nối: "thì", "cứ", ...
        elif low[i] in SPLIT_WEAK:
            score -= 0.06
        if low[i - 1] in GLUE_NEXT:
            score += 0.30  # "mọi | ánh nhìn" -> xấu
        if low[i] in GLUE_PREV:
            score += 0.30  # "mẫu | này" -> xấu
        if f"{low[i - 1]} {low[i]}" in COMPOUNDS:
            score += 0.35  # không cắt giữa từ ghép: "ánh | nhìn", "tự | tin"
        if marked[i] and marked[i - 1]:
            score += 1.0  # không cắt giữa cụm *...*
        if words[i][:1].isupper() and words[i - 1][:1].isupper() and i - 1 > 0:
            score += 1.0  # không cắt giữa cụm viết hoa ("Vibe Gái Hàn")
        if best is None or score < best:
            best, best_i = score, i
    return " ".join(words[:best_i]), " ".join(words[best_i:])


def accent_runs(line: str) -> list[tuple[str, bool]]:
    """Tách dòng đậm thành các đoạn (chữ, có tô màu nhấn không).
    Ưu tiên: *đánh dấu* > cụm Viết Hoa giữa câu > từ khoá thời trang > 2 chữ cuối."""
    if "*" in line:
        parts = line.split("*")
        runs = [(t, k % 2 == 1) for k, t in enumerate(parts) if t]
        return runs if any(r[1] for r in runs) else [(line.replace("*", ""), False)]
    words = line.split()
    if len(words) < 2:
        return [(line, False)]
    key = [re.sub(r"[^\w]", "", w.lower()) for w in words]
    span = None
    run = [k for k in range(1, len(words)) if words[k][:1].isupper()]
    if run:  # cụm viết hoa dài nhất (không tính chữ đầu câu)
        groups, cur = [], [run[0]]
        for k in run[1:]:
            if k == cur[-1] + 1:
                cur.append(k)
            else:
                groups.append(cur)
                cur = [k]
        groups.append(cur)
        g = max(groups, key=len)
        span = (g[0], g[-1] + 1)
    if span is None:
        for phrase in sorted(ACCENT_KEYS, key=lambda x: -len(x.split())):
            pk = phrase.split()
            for k in range(len(key) - len(pk) + 1):
                if key[k:k + len(pk)] == pk:
                    span = (k, k + len(pk))
                    break
            if span:
                break
    if span is None:  # 2 chữ cuối, bỏ qua từ đệm cuối câu ("nha", "nhé", "luôn"...)
        end = len(words)
        while end > 1 and key[end - 1] in PARTICLES:
            end -= 1
        span = (max(0, end - 2), end)
    i, j = span
    runs = []
    if i:
        runs.append((" ".join(words[:i]) + " ", False))
    runs.append((" ".join(words[i:j]), True))
    if j < len(words):
        runs.append((" " + " ".join(words[j:]), False))
    return runs


def load_bank() -> list[str]:
    lines = HOOK_BANK.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]


def auto_hook() -> str:
    bank = load_bank()
    try:
        used = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        used = []
    fresh = [h for h in bank if h not in used] or bank
    hook = random.choice(fresh)
    used = (used + [hook])[-max(1, len(bank) - 3):]
    HISTORY.write_text(json.dumps(used, ensure_ascii=False, indent=0), encoding="utf-8")
    return hook


def resolve_hook(args, clips: list[Path]) -> tuple[str, str]:
    if args.hook and dz.clean_text(args.hook):
        return split_hook(args.hook)
    folder = clips[0].parent
    hook_file = folder / "hook.txt"
    if hook_file.exists():
        lines = [l.strip() for l in hook_file.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        if len(lines) >= 2:
            return split_hook(f"{lines[0]} | {lines[1]}")
        if lines:
            return split_hook(lines[0])
    b1 = hook_from_b1(folder)
    if b1:
        print(f"Lấy hook từ tên file b1: {b1}")
        return split_hook(b1)
    return split_hook(auto_hook())


def hook_from_b1(folder: Path) -> str | None:
    """Quy ước thư mục: ảnh bìa tên 'b1<câu hook>' (có hoặc không có đuôi ảnh)."""
    for f in sorted(folder.iterdir()):
        name = f.stem if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else f.name
        m = re.match(r"^b1(?![0-9])\s*(.*\S)", name, flags=re.IGNORECASE)
        if f.is_file() and m and dz.clean_text(m.group(1)):
            return m.group(1)
    return None


# ---------- render ----------

def load_font(spec: dz.FontSpec, size: int, text: str, max_w: int) -> ImageFont.FreeTypeFont:
    """Nạp font theo preset, tự thu nhỏ nếu dòng chữ rộng quá max_w."""
    while True:
        font = ImageFont.truetype(str(dz.FONTS / spec.file), size)
        if spec.variation:
            font.set_variation_by_name(spec.variation)
        if font.getlength(text) <= max_w or size <= 10:
            return font
        size = int(size * 0.95)


def render_overlay(line1: str, line2: str, w: int, h: int, out: Path,
                   head_top: int | None, safe_top: float, design: dz.Design,
                   scale: float = 1.0) -> None:
    """Vẽ hook: dòng nhỏ (line1, có thể rỗng -> chỉ 1 dòng) + dòng đậm (line2) có cụm tô màu nhấn.

    Vùng an toàn luôn được ưu tiên: khối chữ không bao giờ lên trên vạch safe_top
    (tai thỏ / Dynamic Island / thanh tiêu đề Reels). Vừa khoảng trống trên đầu thì căn giữa
    khoảng đó; không vừa thì bám sát vạch an toàn (phần dưới khối chữ chạm tới đầu người mẫu).
    """
    p = design.preset
    max_w = int(w * MAX_TEXT_W)

    def prep(spec, text):  # font thật sự dùng (dự phòng nếu thiếu glyph) + các đoạn chữ đã an toàn
        runs = accent_runs(text) if spec is p.line2 else [(text.replace("*", ""), False)]
        if spec.upper:
            runs = [(r.upper(), acc) for r, acc in runs]
        real, _, notes = dz.glyph_safe(spec, "".join(r for r, _ in runs))
        for note in notes:
            print(f"[font] {note}")
        runs = [(dz.glyph_safe(real, r)[1] if r.strip() else r, acc) for r, acc in runs]
        font = load_font(real, round(w * real.size * scale), "".join(r for r, _ in runs), max_w)
        return font, runs

    lines = []  # (font, runs, màu thường)
    if line1.strip():
        lines.append((*prep(p.line1, line1), design.color1))
    lines.append((*prep(p.line2, line2), design.color2))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # vị trí tâm từng dòng (dòng đầu tại 0), khoảng cách tâm >= 1.25 line-height
    centers = [0]
    for (fa, _, _), (fb, _, _) in zip(lines, lines[1:]):
        centers.append(centers[-1] + round((fa.size + fb.size) / 2 * LINE_GAP))
    tops, bots = [], []
    for (font, runs, _), cy in zip(lines, centers):
        box = draw.textbbox((w / 2, cy), "".join(r for r, _ in runs), font=font, anchor="mm")
        tops.append(box[1])
        bots.append(box[3])
    block_top, block_bot = min(tops), max(bots)
    safe_px = round(h * safe_top)
    if head_top is None or head_top - safe_px <= 0:
        y0 = safe_px - block_top  # không thấy người: bám vạch an toàn
    else:
        y0 = round((safe_px + head_top) / 2 - (block_top + block_bot) / 2)
    y0 = max(y0, safe_px - block_top)

    for (font, runs, color), cy in zip(lines, centers):
        text = "".join(r for r, _ in runs)
        width = font.getlength(text)
        ascent, descent = font.getmetrics()
        baseline = y0 + cy + (ascent - descent) / 2  # cùng đường chân chữ với anchor "mm"
        x = w / 2 - width / 2
        for r, acc in runs:  # vẽ từng đoạn trên cùng 1 đường chân chữ, đoạn nhấn đổi màu
            draw.text((x, baseline), r, font=font, fill=design.accent if acc else color, anchor="ls")
            x += font.getlength(r)
    img.save(out)


# Bản cuối dùng x264 "veryfast": trên Xeon E5 v2 nhanh ~2x so với "fast", SSIM 0.994 vs 0.996 (khó thấy).
def enc_threads() -> list[str]:
    """VHM_CPU_THREADS cũng giới hạn luồng mã hoá video (mặc định: ffmpeg dùng hết CPU)."""
    return ["-threads", str(devmod.cpu_threads())] if os.environ.get("VHM_CPU_THREADS") else []


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats", *args], check=True)


def seg_frames(ts: float, te: float, speed: float, fps: int) -> int:
    """Số frame đầu ra của một đoạn (mỗi đoạn luôn đúng số nguyên frame)."""
    return max(1, round((te - ts) / speed * fps))


def render_base(clips: list[Path], infos: list[dict], w: int, h: int, fps: int, args, out: Path) -> None:
    """Cắt phần thừa + ghép + đổi tốc độ tất cả clip thành 1 video nền chất lượng cao (file tạm)."""
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    parts, concat_in, n = [], "", 0
    for i, info in enumerate(infos):
        sp = info["speed"]
        segs = info["segments"]
        has_audio = info["audio"] and not args.mute
        k = len(segs)
        vsrc = [f"[{i}:v]"] if k == 1 else [f"[vs{i}_{j}]" for j in range(k)]
        if k > 1:
            parts.append(f"[{i}:v]split={k}" + "".join(vsrc))
        if has_audio:
            asrc = [f"[{i}:a]"] if k == 1 else [f"[as{i}_{j}]" for j in range(k)]
            if k > 1:
                parts.append(f"[{i}:a]asplit={k}" + "".join(asrc))
        for j, (ts, te) in enumerate(segs):
            nf = seg_frames(ts, te, sp, fps)
            dur = nf / fps
            # ép đúng nf frame (tpad bù nếu thiếu, trim bỏ nếu dư) -> ranh giới cảnh chính xác tới frame
            parts.append(f"{vsrc[j]}trim=start={ts:.3f}:end={te:.3f},setpts=(PTS-STARTPTS)/{sp},"
                         f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                         f"crop={w}:{h},setsar=1,fps={fps},format=yuv420p,"
                         f"tpad=stop_mode=clone:stop=3,trim=end_frame={nf},setpts=PTS-STARTPTS[v{n}]")
            if has_audio:
                # hình và tiếng cắt cùng mốc, tăng tốc cùng hệ số -> khớp khẩu hình; atempo giữ cao độ giọng
                fade = min(0.02, dur / 4)
                parts.append(f"{asrc[j]}atrim=start={ts:.3f}:end={te:.3f},asetpts=PTS-STARTPTS,atempo={sp},"
                             f"aresample=44100,aformat=channel_layouts=stereo,apad,atrim=end={dur:.6f},"
                             f"afade=t=in:d={fade:.3f},areverse,afade=t=in:d={fade:.3f},areverse[a{n}]")
            else:
                parts.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={dur:.6f}[a{n}]")
            concat_in += f"[v{n}][a{n}]"
            n += 1
    parts.append(f"{concat_in}concat=n={n}:v=1:a=1[vc][ac]")
    ffmpeg(*inputs, "-filter_complex", ";".join(parts), "-map", "[vc]", "-map", "[ac]",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", *enc_threads(), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "256k", str(out))


def load_rvm(device: str | None = None):
    import torch

    warnings.filterwarnings("ignore", message=r".*torch\.jit\.load.*", category=FutureWarning)

    if device is None:
        prof = devmod.load()
        if prof:  # cấu hình Setup.bat đã kiểm tra thật trên máy này
            device = prof["rvm_device"]
        else:
            device = "cuda" if torch.cuda.is_available() and not devmod.force_cpu() else "cpu"
    if device == "cpu":
        torch.set_num_threads(devmod.cpu_threads())
    return torch.jit.load(str(RVM_MODEL), map_location=device).eval(), device


def matte_size(w: int, h: int, device: str) -> tuple[int, int]:
    prof = devmod.load()
    if prof and prof.get("rvm_device") == device:
        limit = prof["matte_width"]  # theo sức máy đã đo lúc Setup
    else:
        limit = 1080 if device == "cuda" else 720  # CPU: giảm độ phân giải cho nhanh
    mw = min(w, limit) // 2 * 2
    return mw, round(h * mw / w) // 2 * 2


def warm_up_rvm(rvm, w: int, h: int, runs: int = 5) -> None:
    """Chạy vài frame giả đúng kích thước thật để TorchScript tối ưu xong trước khi tách nền."""
    import torch

    model, device = rvm
    mw, mh = matte_size(w, h, device)
    x = torch.zeros(1, 3, mh, mw, device=device)
    rec = [None] * 4
    with torch.no_grad():
        for _ in range(runs):
            _fgr, _pha, *rec = model(x, *rec, min(1.0, 512 / max(mw, mh)))
    if device == "cuda":
        torch.cuda.synchronize()


def grab_frames(video: Path, frame_ids: list[int], aw: int, ah: int) -> dict[int, np.ndarray]:
    """Lấy nhiều frame (theo số thứ tự) chỉ với 1 lần giải mã video."""
    ids = sorted(set(frame_ids))
    sel = "+".join(f"eq(n\\,{i})" for i in ids)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-an",
                          "-vf", f"select='{sel}',scale={aw}:{ah}", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    size = aw * ah * 3
    frames = [np.frombuffer(raw[k * size:(k + 1) * size], np.uint8).reshape(ah, aw, 3)
              for k in range(len(raw) // size)]
    return dict(zip(ids, frames))


def person_mask(rvm, rgb: np.ndarray) -> np.ndarray:
    import torch

    model, device = rvm
    with torch.no_grad():
        src = torch.from_numpy(rgb.copy()).to(device).permute(2, 0, 1)[None].float().div_(255)
        pha = model(src, None, None, None, None, min(1.0, 512 / max(rgb.shape[:2])))[1]
    return pha[0, 0].cpu().numpy()


def analyze_clips(rvm, base: Path, infos: list[dict], fps: int, w: int, h: int,
                  head_top: int | None, safe_top: float, hook_dur: float) -> dz.Features:
    """Lấy mẫu khung hình từng clip: màu trang phục (người) + màu nền vùng đặt chữ (clip 1)."""
    aw = 360
    ah = round(h * aw / w) // 2 * 2
    starts = np.cumsum([0] + [i["frames"] for i in infos])
    picks = {ci: [int(starts[ci] + info["frames"] * f) for f in (0.25, 0.5, 0.75)] for ci, info in enumerate(infos)}
    band_ids = [min(int(fps * 0.05), max(0, int(infos[0]["frames"]) - 1)), int(hook_dur * 0.5 * fps)]
    frames = grab_frames(base, [i for ids in picks.values() for i in ids] + band_ids, aw, ah)
    outfit_px = []
    for ci, info in enumerate(infos):
        px = []
        for fid in picks[ci]:
            if fid not in frames:
                continue
            rgb = frames[fid]
            m = person_mask(rvm, rgb) > 0.6
            rows = np.nonzero(m.any(axis=1))[0]
            if len(rows) < 10:
                continue
            top, bot = rows[0], rows[-1]
            body = np.zeros_like(m)
            body[top + int((bot - top) * 0.22):bot] = True  # bỏ vùng đầu/mặt
            px.append(rgb[m & body])
        outfit_px.append(np.concatenate(px) if px else np.zeros((0, 3), np.uint8))

    y0 = round(ah * safe_top)
    y1 = round(head_top * ah / h) if head_top else y0 + round(ah * 0.12)
    y1 = max(y1, y0 + 8)
    band = []
    for fid in band_ids:
        if fid not in frames:
            continue
        rgb = frames[fid]
        bg = person_mask(rvm, rgb) < 0.3
        band.append(rgb[y0:y1][bg[y0:y1]])
    return dz.analyze(outfit_px, np.concatenate(band))


def matte_video(rvm, base: Path, w: int, h: int, fps: int, nframes: int,
                alpha_out: Path) -> tuple[int | None, int, np.ndarray | None]:
    """Tách người bằng Robust Video Matting cho nframes đầu, ghi alpha (xám 8-bit, thô) ra alpha_out.
    Trả về (đỉnh đầu theo khung w x h, số frame alpha đã ghi, alpha frame đầu tiên = thumbnail)."""
    import torch

    model, device = rvm
    mw, mh = matte_size(w, h, device)
    ratio = min(1.0, 512 / max(mw, mh))

    import queue
    import threading

    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(base), "-frames:v", str(nframes),
                               "-vf", f"scale={mw}:{mh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE, bufsize=mw * mh * 3 * 4)  # đệm lớn: đọc 1 frame/lần
    writer = open(alpha_out, "wb", buffering=mw * mh * 4)  # ghi thô, không nén: nhanh hơn ffv1
    frame_bytes = mw * mh * 3
    probe_frames = max(1, round(fps * 0.2))  # đo đỉnh đầu trong 0.2s đầu
    inq: queue.Queue = queue.Queue(maxsize=8)  # frame đã giải mã, chờ GPU
    outq: queue.Queue = queue.Queue(maxsize=8)  # alpha trên GPU, chờ ghi ra file
    state = {"written": 0, "first": None, "tops": []}

    def read_frames():  # CPU giải mã frame tiếp theo trong lúc GPU đang tính frame hiện tại
        for _ in range(nframes):
            buf = reader.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            inq.put(torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(mh, mw, 3).copy()).pin_memory()
                    if device == "cuda" else torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(mh, mw, 3).copy()))
        inq.put(None)

    def write_alpha():  # chép alpha về CPU + ghi file song song với GPU
        while (pha := outq.get()) is not None:
            alpha = pha.cpu().numpy()
            writer.write(alpha.tobytes())
            idx = state["written"]
            if idx == 0:
                state["first"] = alpha
            if idx < probe_frames:
                rows = np.nonzero((alpha > 128).sum(axis=1) > mw * 0.005)[0]
                if len(rows):
                    state["tops"].append(rows[0])
            state["written"] = idx + 1
            print(f"\rTách nền: {idx + 1}/{nframes}", end="", flush=True)

    tr = threading.Thread(target=read_frames, daemon=True)
    tw = threading.Thread(target=write_alpha, daemon=True)
    tr.start()
    tw.start()
    rec = [None] * 4
    try:
        with torch.no_grad():
            while (frame := inq.get()) is not None:
                src = frame.to(device, non_blocking=True).permute(2, 0, 1)[None].float().div_(255)
                _fgr, pha, *rec = model(src, *rec, ratio)
                outq.put(pha[0, 0].mul(255).byte())
        outq.put(None)
        tw.join()
        tr.join()
    finally:  # GPU lỗi giữa chừng: dừng ffmpeg + đóng file để lần làm lại (CPU) bắt đầu sạch
        if tw.is_alive():
            outq.put(None)
        reader.kill()
        reader.stdout.close()
        reader.wait()
        tw.join(timeout=10)
        writer.close()
    print()
    written, first_alpha, tops = state["written"], state["first"], state["tops"]
    return (round(float(np.median(tops)) * h / mh) if tops else None), written, first_alpha


def build(clips: list[Path], line1: str, line2: str, out: Path, args) -> None:
    prof = devmod.load()
    if prof is None:  # vd vừa cập nhật bằng nút Cập nhật: kiểm tra thiết bị 1 lần (~10 giây)
        print("Kiểm tra GPU/CPU lần đầu để chọn cấu hình hợp máy ...")
        try:
            prof = devmod.detect()
        except Exception as e:
            print(f"  (không kiểm tra được: {e}; dùng cấu hình mặc định)")
    print("Thiết bị:", devmod.describe(prof) if prof else "mặc định")
    infos = [probe(c) for c in clips]
    for c, info in zip(clips, infos):
        full = info["duration"]
        info["segments"], st = [(0.0, full)], None
        if info["audio"] and not args.no_trim:
            info["segments"], st = speech_segments(c, full)
        info["duration"] = sum(e - s for s, e in info["segments"])
        msg = f"  {c.name}: {full:.2f}s -> {info['duration']:.2f}s"
        if st and full - info["duration"] > 0.01:
            msg += (f" (cắt đầu {st['head']:.2f}s, cuối {st['tail']:.2f}s, "
                    f"{st['pauses']} khoảng ngừng {st['pause_s']:.2f}s)")
        print(msg)
    first = infos[0]
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
    else:
        w, h = first["width"], first["height"]
    w, h = w - w % 2, h - h % 2
    # Nạp torch + model tách nền và "khởi động" nó song song trong lúc Whisper chạy / ghép clip:
    # TorchScript mất vài giây tối ưu ở những lần gọi đầu, làm trước thì lúc tách nền thật đã sẵn sàng.
    rvm_box: dict = {}

    def preload():
        try:
            rvm = load_rvm()
            try:
                if args.text_layer != "front":
                    warm_up_rvm(rvm, w, h)
            except Exception as e:  # GPU có nhưng chạy lỗi (card cũ, thiếu VRAM...) -> CPU
                if rvm[1] != "cuda":
                    raise
                print(f"  (GPU lỗi khi khởi động tách nền: {str(e).splitlines()[0][:120]} -> dùng CPU)")
                rvm = load_rvm("cpu")
            rvm_box["rvm"] = rvm
        except Exception as e:  # báo lỗi khi thật sự cần dùng
            rvm_box["err"] = e
    loader = threading.Thread(target=preload, daemon=True)
    loader.start()
    sync_speeds(clips, infos, args)
    fps = args.fps or round(first["fps"])
    for info in infos:
        info["frames"] = sum(seg_frames(s, e, info["speed"], fps) for s, e in info["segments"])
    total_frames = sum(i["frames"] for i in infos)
    if args.hook_dur == "clip1":
        nframes = first["frames"]  # đúng tới frame cuối của cảnh đầu
    else:
        # chữ (và tách nền) tối đa hết cảnh đầu: không tràn sang clip 2
        nframes = min(first["frames"], max(1, round(float(args.hook_dur) * fps)))
    hook_dur = nframes / fps

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, alpha, overlay = tmp / "base.mp4", tmp / "alpha.gray", tmp / "hook.png"
        print("1/3 Ghép clip...")
        render_base(clips, infos, w, h, fps, args, base)

        loader.join()
        if "err" in rvm_box:
            raise rvm_box["err"]
        rvm = rvm_box["rvm"]
        head_top, first_alpha = None, None
        if args.text_layer != "front":
            print("2/3 Tách người khỏi nền...")
            try:
                head_top, written, first_alpha = matte_video(rvm, base, w, h, fps, nframes, alpha)
            except Exception as e:  # GPU lỗi / tràn VRAM giữa chừng -> làm lại bằng CPU, không dừng
                if rvm[1] != "cuda":
                    raise
                print(f"\n  (GPU lỗi khi tách nền: {str(e).splitlines()[0][:120]} -> làm lại bằng CPU)")
                rvm = load_rvm("cpu")
                head_top, written, first_alpha = matte_video(rvm, base, w, h, fps, nframes, alpha)
            nframes = max(1, written)  # khớp đúng số frame thật của cảnh đầu
            hook_dur = nframes / fps
            print(f"Đỉnh đầu ở y={head_top}/{h}" if head_top else "Không thấy người, dùng vị trí mặc định.")

        print("Phân tích clip để thiết kế chữ...")
        feats = analyze_clips(rvm, base, infos, fps, w, h, head_top, args.safe_top, hook_dur)
        design = dz.choose_design(f"{line1} {line2}", feats, args.style)
        print(design.summary())
        render = lambda sc: render_overlay(line1, line2, w, h, overlay, head_top, args.safe_top, design, sc)

        def coverage() -> float:
            text_a = np.asarray(Image.open(overlay).getchannel("A").resize(first_alpha.shape[::-1])) > 128
            return float((text_a & (first_alpha > 128)).sum() / max(1, text_a.sum()))

        # Ưu tiên chữ TO nhưng không để người mẫu che chữ ở frame đầu (thumbnail):
        # thử cỡ 100% -> 80%, cỡ lớn nhất bị che <= OCCLUDE_MAX thì giữ chữ SAU người mẫu.
        # Không cỡ nào đạt thì đưa chữ lên TRƯỚC, chọn cỡ che ít người nhất (đỡ đè lên mặt).
        behind = args.text_layer == "behind"
        render(1.0)
        if behind and first_alpha is not None:
            print(f"Chữ nằm SAU người mẫu, cỡ lớn nhất; frame đầu tóc/đầu che {coverage():.0%} chữ")
        if args.text_layer == "auto" and first_alpha is not None:
            tried = []
            for sc in (1.0, 0.9, 0.8):
                render(sc)
                tried.append((coverage(), sc))
                if tried[-1][0] <= OCCLUDE_MAX:
                    behind = True
                    break
            covered, sc = tried[-1] if behind else min(tried)
            if not behind:
                render(sc)
            print(f"Thumbnail (frame đầu): người mẫu chạm {covered:.0%} chữ ở cỡ {sc:.0%} -> "
                  + ("chữ nằm SAU người mẫu" if behind else "đưa chữ lên TRƯỚC người mẫu"))
            if covered > 0.2:
                print("  Gợi ý: clip đầu thiếu khoảng trống trên đầu người mẫu. Khi tạo clip, để trống "
                      "~20-25% phía trên khung thì chữ vừa to vừa nằm sau người được.")
        if args.keep_png:
            Image.open(overlay).save(out.with_suffix(".hook.png"))
            out.with_suffix(".design.txt").write_text(design.summary(), encoding="utf-8")

        if first_alpha is None:  # không tách được người (vd không có frame) -> chữ nằm trên
            behind = False
        print("3/3 Xếp lớp: " + ("video gốc -> text -> người đã tách nền..." if behind else "video gốc -> text..."))
        enable = f"enable='lt(t,{hook_dur:.4f})'"
        if not behind:
            fc = f"[0:v][1:v]overlay=0:0:{enable}[v]"
            extra = []
        else:
            fc = (f"[0:v]split[b][f];[b][1:v]overlay=0:0:{enable}[bt];"
                  f"[f]trim=end_frame={nframes},setpts=PTS-STARTPTS[ft];"
                  f"[2:v]scale={w}:{h}:flags=bicubic,format=gray[a];"
                  f"[ft][a]alphamerge[fg];[bt][fg]overlay=0:0:eof_action=pass[v]")
            ah, aw = first_alpha.shape
            extra = ["-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{aw}x{ah}", "-r", str(fps), "-i", str(alpha)]
        ffmpeg("-i", str(base), "-loop", "1", "-t", f"{hook_dur:.4f}", "-i", str(overlay), *extra,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf), *enc_threads(), "-pix_fmt", "yuv420p",
               "-c:a", "copy", "-movflags", "+faststart", str(out))


def main() -> None:
    ap = argparse.ArgumentParser(description="Ghép clip + tự tạo hook text 2 dòng nằm sau người mẫu.")
    ap.add_argument("inputs", nargs="+", help="Thư mục chứa clip hoặc danh sách file clip (ghép theo thứ tự tên)")
    ap.add_argument("-o", "--output", help="File MP4 đầu ra (mặc định: <thư mục clip>/<tên thư mục>_hook.mp4, không ghi đè)")
    ap.add_argument("--hook", help='Text hook, vd "Không biết phối đồ đi tiệc | Cứ mặc nguyên set này"')
    ap.add_argument("--hook-dur", default="clip1",
                    help="Thời gian hiện text: \"clip1\" = hết cảnh đầu (mặc định), hoặc số giây, vd 4")
    ap.add_argument("--speed", type=float, default=1.15,
                    help="Tốc độ hình + giọng nói (mặc định 1.15, nhanh hơn mẫu 1.1 một chút; giữ cao độ giọng)")
    ap.add_argument("--no-sync-speed", action="store_true",
                    help="Không đồng bộ tốc độ nói giữa các clip (mọi clip dùng đúng --speed)")
    ap.add_argument("--no-trim", action="store_true", help="Không cắt khoảng lặng (đầu, cuối, ngừng giữa câu)")
    ap.add_argument("--safe-top", type=float, default=0.08,
                    help="Vùng cấm phía trên (tỉ lệ chiều cao) cho tai thỏ/Dynamic Island + hàng icon Reels "
                         "(mặc định 0.08; 0.14 = khuyến nghị chặt của Meta)")
    ap.add_argument("--style", choices=list(dz.PRESETS),
                    help="Ép phong cách chữ thay vì tự chọn: " + ", ".join(dz.PRESETS))
    ap.add_argument("--ask", action="store_true", help="Hỏi nhập hook và tốc độ trong cửa sổ (dùng cho file .bat)")
    ap.add_argument("--size", help="Kích thước đầu ra WxH, vd 1080x1920 (mặc định = clip đầu)")
    ap.add_argument("--fps", type=int, help="FPS đầu ra (mặc định = clip đầu)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--mute", action="store_true", help="Bỏ âm thanh gốc của clip")
    ap.add_argument("--text-layer", choices=["behind", "auto", "front"], default="behind",
                    help="behind (mặc định): chữ luôn sau người mẫu, tóc đè lên chữ; "
                         "auto: đưa chữ lên trước nếu frame đầu bị che >4%% chữ; front: luôn trước người")
    ap.add_argument("--keep-png", action="store_true", help="Lưu thêm ảnh PNG của lớp text để xem trước")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if args.ask and not args.hook:
        # làm sạch trước: ký tự vô hình (BOM, zero-width) khi dán chữ không được tính là "đã nhập"
        args.hook = dz.clean_text(input('Nhập hook ("dòng 1 | dòng 2", Enter = tự lấy từ hook.txt / '
                                        'tên file b1 / kho hook): ')) or None
    if args.ask:
        while True:
            raw = input(f"Tốc độ video + giọng (Enter = {args.speed}, vd 1.2): ").strip().replace(",", ".")
            try:
                sp = float(raw) if raw else args.speed
            except ValueError:
                sp = 0
            if 0.5 <= sp <= 2.0:
                args.speed = sp
                break
            print("  Nhập số từ 0.5 đến 2.0")
    if not 0.5 <= args.speed <= 2.0:
        sys.exit("--speed phải trong khoảng 0.5 đến 2.0")
    if not RVM_MODEL.exists():
        sys.exit(f"Thiếu model tách nền: {RVM_MODEL}\nTải tại: {RVM_URL}")

    clips = collect_clips(args.inputs)
    line1, line2 = resolve_hook(args, clips)
    if not (line1 or line2):
        sys.exit("Hook rỗng (không có chữ nào vẽ được). Hãy nhập lại câu hook.")
    if args.output:
        out = Path(args.output)
    else:
        src = Path(args.inputs[0])
        base = src if src.is_dir() else src.parent
        out = base / f"{base.name}_hook.mp4"  # nằm trong thư mục clip (file *_hook không bị ghép lại)
        k = 2
        while out.exists():  # không ghi đè video cũ
            out = base / f"{base.name}_hook_{k}.mp4"
            k += 1
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Ghép {len(clips)} clip:", *[f"  - {c.name}" for c in clips], sep="\n")
    print(f"Hook: {line1}  /  {line2}" if line1 else f"Hook (1 dòng): {line2}")
    build(clips, line1, line2, out, args)
    print(f"Xong: {out}")


if __name__ == "__main__":
    main()
