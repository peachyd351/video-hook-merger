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
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import warnings

import numpy as np

from PIL import Image, ImageDraw, ImageFont

import design as dz

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

# Từ mở vế sau, dùng để tự tách 1 câu thành 2 dòng.
SPLIT_WORDS = ["thì", "cứ", "chỉ cần", "hãy", "mặc", "chọn", "đây là", "là", "vì", "nhưng", "mà"]


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
    try:
        import torch
        devices = ["cuda", "cpu"] if torch.cuda.is_available() else ["cpu"]
    except Exception:
        devices = ["cpu"]
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
    a, b = _split(text)
    return cap(a.rstrip(" ,:;–—-")), cap(b.lstrip(" ,:;–—-"))


def _split(text: str) -> tuple[str, str]:
    text = dz.clean_text(text)
    if "|" in text:
        a, b = text.split("|", 1)
        return a.strip(), b.strip()
    for sep in [",", " – ", " — ", " - ", ":", "…", "..."]:
        if sep in text:
            a, b = text.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    words = text.split()
    low = [w.lower() for w in words]
    for kw in SPLIT_WORDS:
        k = kw.split()
        for i in range(2, len(words) - 1):
            if low[i:i + len(k)] == k:
                return " ".join(words[:i]), " ".join(words[i:])
    cut = max(1, round(len(words) * 0.5))
    return " ".join(words[:cut]), " ".join(words[cut:])


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
    """Vẽ 2 dòng chữ ở cỡ `scale` (1.0 = lớn nhất theo preset).

    Vùng an toàn luôn được ưu tiên: khối chữ không bao giờ lên trên vạch safe_top
    (tai thỏ / Dynamic Island / thanh tiêu đề Reels). Vừa khoảng trống trên đầu thì căn giữa
    khoảng đó; không vừa thì bám sát vạch an toàn (phần dưới khối chữ chạm tới đầu người mẫu).
    """
    p = design.preset
    spec1, line1, n1 = dz.glyph_safe(p.line1, line1.upper() if p.line1.upper else line1)
    spec2, line2, n2 = dz.glyph_safe(p.line2, line2.upper() if p.line2.upper else line2)
    for note in n1 + n2:
        print(f"[font] {note}")
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_w = int(w * MAX_TEXT_W)
    safe_px = round(h * safe_top)
    room = (head_top - safe_px) if head_top else None
    f1 = load_font(spec1, round(w * spec1.size * scale), line1, max_w)
    f2 = load_font(spec2, round(w * spec2.size * scale), line2, max_w)
    gap = round((f1.size + f2.size) / 2 * LINE_GAP)
    block_top = draw.textbbox((w / 2, 0), line1, font=f1, anchor="mm")[1]
    block_bot = draw.textbbox((w / 2, gap), line2, font=f2, anchor="mm")[3]
    if room is None:
        y1 = safe_px - block_top  # không thấy người: bám vạch an toàn
    else:
        y1 = round((safe_px + head_top) / 2 - (block_top + block_bot) / 2)
    y1 = max(y1, safe_px - block_top)

    draw.text((w / 2, y1), line1, font=f1, fill=design.color1, anchor="mm")
    draw.text((w / 2, y1 + gap), line2, font=f2, fill=design.color2, anchor="mm")
    img.save(out)


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
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "256k", str(out))


def load_rvm():
    import torch

    warnings.filterwarnings("ignore", message=r".*torch\.jit\.load.*", category=FutureWarning)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    return torch.jit.load(str(RVM_MODEL), map_location=device).eval(), device


def grab_frame(video: Path, t: float, aw: int, ah: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(ah, aw, 3)


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
    starts = np.cumsum([0.0] + [i["frames"] / fps for i in infos])
    outfit_px = []
    for ci, info in enumerate(infos):
        dur = info["frames"] / fps
        px = []
        for frac in (0.25, 0.5, 0.75):
            rgb = grab_frame(base, starts[ci] + dur * frac, aw, ah)
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
    for t in (0.05, hook_dur * 0.5):
        rgb = grab_frame(base, t, aw, ah)
        bg = person_mask(rvm, rgb) < 0.3
        band.append(rgb[y0:y1][bg[y0:y1]])
    return dz.analyze(outfit_px, np.concatenate(band))


def matte_video(rvm, base: Path, w: int, h: int, fps: int, nframes: int,
                alpha_out: Path) -> tuple[int | None, int, np.ndarray | None]:
    """Tách người bằng Robust Video Matting cho nframes đầu, ghi alpha ra video xám.
    Trả về (đỉnh đầu theo khung w x h, số frame alpha đã ghi, alpha frame đầu tiên = thumbnail)."""
    import torch

    model, device = rvm
    mw = min(w, 1080 if device == "cuda" else 720) // 2 * 2  # CPU: giảm độ phân giải cho nhanh
    mh = round(h * mw / w) // 2 * 2
    ratio = min(1.0, 512 / max(mw, mh))

    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(base), "-frames:v", str(nframes),
                               "-vf", f"scale={mw}:{mh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
                               "-s", f"{mw}x{mh}", "-r", str(fps), "-i", "-", "-c:v", "ffv1", str(alpha_out)],
                              stdin=subprocess.PIPE)
    rec = [None] * 4
    written = 0
    first_alpha = None
    tops = []
    frame_bytes = mw * mh * 3
    probe_frames = max(1, round(fps * 0.2))  # đo đỉnh đầu trong 0.2s đầu
    with torch.no_grad():
        for idx in range(nframes):
            buf = reader.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            src = torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(mh, mw, 3).copy())
            src = src.to(device).permute(2, 0, 1)[None].float().div_(255)
            _fgr, pha, *rec = model(src, *rec, ratio)
            alpha = pha[0, 0].mul(255).byte().cpu().numpy()
            writer.stdin.write(alpha.tobytes())
            written = idx + 1
            if idx == 0:
                first_alpha = alpha
            if idx < probe_frames:
                rows = np.nonzero((alpha > 128).sum(axis=1) > mw * 0.005)[0]
                if len(rows):
                    tops.append(rows[0])
            print(f"\rTách nền: {idx + 1}/{nframes}", end="", flush=True)
    print()
    reader.stdout.close()
    reader.wait()
    writer.stdin.close()
    writer.wait()
    return (round(float(np.median(tops)) * h / mh) if tops else None), written, first_alpha


def build(clips: list[Path], line1: str, line2: str, out: Path, args) -> None:
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
    sync_speeds(clips, infos, args)
    first = infos[0]
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
    else:
        w, h = first["width"], first["height"]
    w, h = w - w % 2, h - h % 2
    fps = args.fps or round(first["fps"])
    for info in infos:
        info["frames"] = sum(seg_frames(s, e, info["speed"], fps) for s, e in info["segments"])
    total_frames = sum(i["frames"] for i in infos)
    if args.hook_dur == "clip1":
        nframes = first["frames"]  # đúng tới frame cuối của cảnh đầu
    else:
        nframes = min(total_frames, max(1, round(float(args.hook_dur) * fps)))
    hook_dur = nframes / fps

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, alpha, overlay = tmp / "base.mp4", tmp / "alpha.mkv", tmp / "hook.png"
        print("1/3 Ghép clip...")
        render_base(clips, infos, w, h, fps, args, base)

        rvm = load_rvm()
        head_top, first_alpha = None, None
        if args.text_layer != "front":
            print("2/3 Tách người khỏi nền...")
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
            extra = ["-i", str(alpha)]
        ffmpeg("-i", str(base), "-loop", "1", "-t", f"{hook_dur:.4f}", "-i", str(overlay), *extra,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
               "-c:a", "copy", "-movflags", "+faststart", str(out))
    cover = out.with_suffix(".cover.jpg")
    ffmpeg("-i", str(out), "-frames:v", "1", "-q:v", "2", str(cover))
    print(f"Ảnh cover (frame đầu): {cover}")


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
    print(f"Hook: {line1}  /  {line2}")
    build(clips, line1, line2, out, args)
    print(f"Xong: {out}")


if __name__ == "__main__":
    main()
