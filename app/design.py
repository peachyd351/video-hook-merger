"""Tự thiết kế font + màu cho hook text dựa trên nội dung 3 clip và câu text.

Đầu vào (đã chuẩn bị sẵn bởi hook_merge.py):
  - outfit_px: điểm ảnh RGB thuộc người mẫu (vùng trang phục) của từng clip
  - band_px:   điểm ảnh RGB nền ở vùng đặt chữ (clip 1, đã loại người)
  - text:      câu hook

Đầu ra: Design gồm bộ font (preset), màu dòng 1, màu dòng 2, lý do chọn.
Không dùng hiệu ứng: chỉ font, màu và vị trí.
Mọi thứ chạy offline, cùng input -> cùng kết quả.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FONTS = Path(__file__).resolve().parent / "fonts"


@dataclass
class FontSpec:
    file: str
    size: float  # cỡ chữ / chiều rộng khung
    variation: str | None = None
    upper: bool = False


@dataclass
class Preset:
    name: str
    label: str
    line1: FontSpec
    line2: FontSpec
    use_accent: bool  # dòng 2 được phép lấy màu nhấn từ trang phục


# Cỡ chữ đo theo video mẫu "Nàng mặc đẹp" (dòng 1 nhỏ nghiêng mảnh, dòng 2 serif Bold ~75% bề ngang).
PRESETS = {
    "sang_trong": Preset("sang_trong", "Sang trọng (tiệc, sự kiện)",
                         FontSpec("BeVietnamPro-LightItalic.ttf", 0.058),
                         FontSpec("PlayfairDisplay.ttf", 0.074, "Bold"), use_accent=False),
    "tap_chi": Preset("tap_chi", "Tạp chí (thanh lịch, tối giản sang)",
                      FontSpec("BeVietnamPro-Light.ttf", 0.052),
                      FontSpec("Fraunces-SemiBoldItalic.ttf", 0.078), use_accent=True),
    "lang_man": Preset("lang_man", "Lãng mạn (hẹn hò, cưới, nữ tính)",
                       FontSpec("TH-Viettay-6.ttf", 0.085),
                       FontSpec("Fraunces-SemiBold.ttf", 0.072), use_accent=True),
    "de_thuong": Preset("de_thuong", "Dễ thương (đi chơi, pastel)",
                        FontSpec("TH-Viettay-6.ttf", 0.085),
                        FontSpec("YesevaOne-Regular.ttf", 0.070), use_accent=True),
    "hien_dai": Preset("hien_dai", "Hiện đại (công sở, basic)",
                       FontSpec("BeVietnamPro-Light.ttf", 0.052),
                       FontSpec("BeVietnamPro-ExtraBold.ttf", 0.066), use_accent=False),
    "ca_tinh": Preset("ca_tinh", "Cá tính (màu nổi, street)",
                      FontSpec("BeVietnamPro-MediumItalic.ttf", 0.052),
                      FontSpec("UTM Bebas.ttf", 0.112, upper=True), use_accent=True),
}

KEYWORDS = {
    "sang_trong": ["tiệc", "sự kiện", "dạ hội", "sang", "quý phái", "tiểu thư", "gala", "sang chảnh", "đẳng cấp"],
    "tap_chi": ["ren", "lụa", "thanh lịch", "tinh tế", "tối giản", "quý cô", "kiêu kỳ", "sành điệu"],
    "lang_man": ["hẹn hò", "cưới", "lãng mạn", "ngọt ngào", "nữ tính", "dịu dàng", "valentine", "người yêu", "crush"],
    "de_thuong": ["dễ thương", "cute", "xinh xắn", "đi chơi", "học sinh", "biển", "dã ngoại", "bánh bèo", "trẻ trung"],
    "hien_dai": ["công sở", "đi làm", "văn phòng", "basic", "đơn giản", "hằng ngày", "tối giản", "công thức"],
    "ca_tinh": ["cá tính", "street", "năng động", "phá cách", "nổi bật", "chất", "ngầu", "cool", "sporty"],
}


# ---------- an toàn tiếng Việt ----------

# Font dự phòng (đều phủ đủ 146 ký tự tiếng Việt) khi font chính thiếu glyph.
FALLBACK = {
    "TH-Viettay-6.ttf": FontSpec("BeVietnamPro-LightItalic.ttf", 0.058),
    "UTM Bebas.ttf": FontSpec("BeVietnamPro-ExtraBold.ttf", 0.066),
    "YesevaOne-Regular.ttf": FontSpec("Fraunces-SemiBold.ttf", 0.072),
}
DEFAULT_FALLBACK = FontSpec("BeVietnamPro-Light.ttf", 0.052)
# Dấu câu "đẹp" -> bản ASCII khi font không có.
PUNCT_SWAP = {"–": "-", "—": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'", " ": " "}
_CMAPS: dict[str, set] = {}


def clean_text(text: str) -> str:
    """Chuẩn hoá NFC (dấu dựng sẵn) và bỏ emoji / ký tự vô hình / dấu rời không ghép được."""
    text = unicodedata.normalize("NFC", text)
    keep = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("So", "Cs", "Co", "Cf", "Cc", "Mn") or 0xFE00 <= ord(ch) <= 0xFE0F:
            continue  # emoji ✨, zero-width, dấu kết hợp lẻ
        keep.append(ch)
    return " ".join("".join(keep).split())


def cmap_of(spec: FontSpec) -> set:
    if spec.file not in _CMAPS:
        from fontTools.ttLib import TTFont
        _CMAPS[spec.file] = set(TTFont(str(FONTS / spec.file)).getBestCmap())
    return _CMAPS[spec.file]


def glyph_safe(spec: FontSpec, text: str) -> tuple[FontSpec, str, list[str]]:
    """Đảm bảo mọi ký tự vẽ được bằng font: đổi dấu câu, rồi đổi sang font dự phòng,
    cuối cùng mới bỏ ký tự. Trả về (font dùng thật, text, cảnh báo)."""
    notes = []
    missing = lambda sp, t: [c for c in t if c != " " and ord(c) not in cmap_of(sp)]
    miss = missing(spec, text)
    if miss:
        text = "".join(PUNCT_SWAP.get(c, c) if c in miss else c for c in text)
        miss = missing(spec, text)
    if miss:
        fb = FALLBACK.get(spec.file, DEFAULT_FALLBACK)
        fb = FontSpec(fb.file, fb.size, fb.variation, spec.upper)
        notes.append(f"{spec.file} thiếu '{''.join(sorted(set(miss)))}' -> dùng {fb.file}")
        spec = fb
        miss = missing(spec, text)
    if miss:
        notes.append(f"Bỏ ký tự không font nào vẽ được: '{''.join(sorted(set(miss)))}'")
        text = " ".join("".join(c for c in text if c not in miss).split())
    return spec, text, notes


# ---------- màu: sRGB <-> OKLab / OKLCH, độ tương phản WCAG ----------

def _to_linear(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _from_linear(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055) * 255.0


def rgb_to_oklab(rgb):
    lin = _to_linear(rgb)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


_M2I = np.array([[1.0, 0.3963377774, 0.2158037573],
                 [1.0, -0.1055613458, -0.0638541728],
                 [1.0, -0.0894841775, -1.2914855480]])
_M1I = np.array([[4.0767416621, -3.3077115913, 0.2309699292],
                 [-1.2684380046, 2.6097574011, -0.3413193965],
                 [-0.0041960863, -0.7034186147, 1.7076147010]])


def lch_to_rgb(L, C, h_deg) -> tuple[int, int, int]:
    """OKLCH -> sRGB; giảm chroma dần nếu màu nằm ngoài gam sRGB."""
    h = np.deg2rad(h_deg)
    for c in np.linspace(C, 0, 12):
        lab = np.array([L, c * np.cos(h), c * np.sin(h)])
        lin = (lab @ _M2I.T) ** 3 @ _M1I.T
        if lin.min() >= -1e-4 and lin.max() <= 1 + 1e-4:
            break
    return tuple(int(round(v)) for v in _from_linear(lin))


def luminance(rgb) -> np.ndarray:
    lin = _to_linear(rgb)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def contrast(y1: float, y2: float) -> float:
    hi, lo = max(y1, y2), min(y1, y2)
    return (hi + 0.05) / (lo + 0.05)


def lch_of(lab):
    L, a, b = lab
    return L, float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)) % 360)


# ---------- phân tích ----------

def kmeans(x: np.ndarray, k: int, iters: int = 12, seed: int = 0):
    rng = np.random.default_rng(seed)
    if len(x) <= k:
        return x, np.ones(len(x)) / max(1, len(x))
    centers = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if np.any(lab == j):
                centers[j] = x[lab == j].mean(0)
    counts = np.bincount(lab, minlength=k).astype(float)
    return centers, counts / counts.sum()


def is_skin(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360
    return (h > 25) & (h < 85) & (C > 0.03) & (C < 0.14) & (L > 0.5) & (L < 0.9)


@dataclass
class Features:
    bg_L: float
    bg_C: float
    bg_h: float
    bg_busy: float
    bg_y_lo: float  # luminance nền (phân vị 10%) - xấu nhất cho chữ tối
    bg_y_hi: float  # luminance nền (phân vị 90%) - xấu nhất cho chữ sáng
    outfit_colors: list = field(default_factory=list)  # [(lab, weight, clip_idx)]
    bg_rgb: tuple = (235, 228, 220)  # màu nền trung vị vùng đặt chữ
    vivid: float = 0.0
    pastel: float = 0.0
    dark: float = 0.0
    light: float = 0.0


def analyze(outfit_px: list[np.ndarray], band_px: np.ndarray) -> Features:
    rng = np.random.default_rng(0)
    band = band_px.reshape(-1, 3)
    if len(band) > 40000:
        band = band[rng.choice(len(band), 40000, replace=False)]
    band_lab = rgb_to_oklab(band)
    bg_L, bg_C, bg_h = lch_of(band_lab.mean(0))
    y = luminance(band)
    feats = Features(bg_L, bg_C, bg_h, float(band_lab[:, 0].std()),
                     float(np.percentile(y, 10)), float(np.percentile(y, 90)),
                     bg_rgb=tuple(int(v) for v in np.median(band, axis=0)))

    all_lab = []
    for ci, px in enumerate(outfit_px):
        px = px.reshape(-1, 3)
        if len(px) < 50:
            continue
        if len(px) > 20000:
            px = px[rng.choice(len(px), 20000, replace=False)]
        lab = rgb_to_oklab(px)
        lab = lab[~is_skin(lab)]
        if len(lab) < 50:
            continue
        all_lab.append(lab)
        centers, weights = kmeans(lab, 4, seed=ci)
        feats.outfit_colors += [(c, w / len(outfit_px), ci) for c, w in zip(centers, weights)]
    if all_lab:
        lab = np.concatenate(all_lab)
        C = np.hypot(lab[:, 1], lab[:, 2])
        feats.vivid = float((C > 0.13).mean())
        feats.pastel = float(((lab[:, 0] > 0.75) & (C > 0.03) & (C < 0.12)).mean())
        feats.dark = float((lab[:, 0] < 0.32).mean())
        feats.light = float((lab[:, 0] > 0.85).mean())
    return feats


# ---------- chọn thiết kế ----------

@dataclass
class Design:
    preset: Preset
    color1: tuple
    color2: tuple
    reasons: list

    def summary(self) -> str:
        hx = lambda c: "#%02x%02x%02x" % c[:3]
        s = [f"Phong cách: {self.preset.label}",
             f"Màu dòng 1: {hx(self.color1)}   Màu dòng 2: {hx(self.color2)}"]
        return "\n".join(s + [f"  - {r}" for r in self.reasons])


def score_styles(text: str, f: Features) -> tuple[dict, list]:
    t = unicodedata.normalize("NFC", text.lower())
    score = {k: 0.0 for k in PRESETS}
    score["sang_trong"] += 0.5  # phong cách gốc của kênh
    reasons = []
    for style, words in KEYWORDS.items():
        hits = [w for w in words if w in t]
        if hits:
            score[style] += 2.5 * len(hits)  # ý nghĩa câu text nặng hơn tín hiệu hình
            reasons.append(f"Text có từ khóa {', '.join(hits)} -> {PRESETS[style].label}")
    if f.vivid > 0.25:
        score["ca_tinh"] += 1.5
        reasons.append(f"Trang phục màu nổi ({f.vivid:.0%} điểm ảnh rực)")
    if f.pastel > 0.25:
        score["lang_man"] += 1.0
        score["de_thuong"] += 1.0
        reasons.append(f"Trang phục tông pastel ({f.pastel:.0%})")
    if f.dark > 0.2 and f.light > 0.15:
        score["sang_trong"] += 1.0
        reasons.append(f"Phối tương phản đen/trắng ({f.dark:.0%} tối, {f.light:.0%} sáng)")
    elif f.vivid < 0.08 and f.pastel < 0.15:
        score["hien_dai"] += 0.8
        score["tap_chi"] += 1.0
        reasons.append("Trang phục tông trung tính")
    return score, reasons


def pick_accent(f: Features) -> tuple | None:
    """Màu nhấn = màu trang phục có chroma cao, ưu tiên clip 1 (clip đang hiện chữ)."""
    best, best_score = None, 0.0
    for lab, w, ci in f.outfit_colors:
        L, C, h = lch_of(lab)
        if C < 0.07 or w < 0.03 or L < 0.2:
            continue
        s = C * np.sqrt(w) * (1.5 if ci == 0 else 1.0)
        if s > best_score:
            best, best_score = (L, C, h), s
    return best


def solve_color(L: float, C: float, h: float, dark_text: bool, f: Features, target: float = 4.5):
    """Dịch độ sáng L tới khi đạt tương phản target với phần nền xấu nhất."""
    bg_y = f.bg_y_lo if dark_text else f.bg_y_hi
    step = -0.02 if dark_text else 0.02
    for _ in range(60):
        rgb = lch_to_rgb(L, C, h)
        if contrast(float(luminance(np.array(rgb))), bg_y) >= target:
            return rgb, True
        L = float(np.clip(L + step, 0.05, 0.98))
    return lch_to_rgb(L, C, h), False


def choose_design(text: str, f: Features, style: str | None = None) -> Design:
    score, reasons = score_styles(text, f)
    if style:
        name = style
        reasons = [f"Chọn tay phong cách {style}"]
    else:
        name = max(score, key=lambda k: score[k])
    preset = PRESETS[name]

    # nền sáng -> chữ tối (ngả theo tông nền); nền tối -> chữ sáng
    dark_text = contrast(0.0, f.bg_y_lo) >= contrast(1.0, f.bg_y_hi)
    tone = "sáng" if dark_text else "tối"
    reasons.append(f"Nền vùng chữ {tone} (L={f.bg_L:.2f}, độ rối={f.bg_busy:.2f}) -> chữ {'tối' if dark_text else 'sáng'}")
    tint_c = min(f.bg_C * 0.6 + 0.012, 0.035)
    L1, L2 = (0.40, 0.30) if dark_text else (0.93, 0.97)
    color1, ok1 = solve_color(L1, tint_c, f.bg_h, dark_text, f)
    color2, ok2 = solve_color(L2, tint_c, f.bg_h, dark_text, f)

    accent = pick_accent(f) if preset.use_accent else None
    if accent:
        aL, aC, ah = accent
        aL = min(aL, 0.5) if dark_text else max(aL, 0.8)
        acc_rgb, ok = solve_color(aL, min(aC, 0.16), ah, dark_text, f)
        if ok:
            color2 = acc_rgb
            reasons.append("Dòng 2 lấy màu nhấn từ trang phục: #%02x%02x%02x" % acc_rgb)

    if not (ok1 and ok2):
        reasons.append("Nền vùng chữ tương phản thấp: đã đẩy màu chữ tới mức đậm/nhạt nhất")
    return Design(preset, color1 + (255,), color2 + (255,), reasons)
