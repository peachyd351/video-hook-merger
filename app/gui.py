"""Giao diện đơn giản cho Video Hook Merger (Tkinter, có sẵn trong Python).

  pythonw gui.py [clip1 clip2 clip3 | thư_mục]   # đường dẫn truyền vào được điền sẵn
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import design as dz  # noqa: E402  (chỉ lấy tên phong cách, không nạp torch)
import updater  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SETTINGS = ROOT / ".gui_settings.json"
STYLE_AUTO = "Tự động (theo câu hook + trang phục)"
STYLES = {STYLE_AUTO: None, **{p.label: key for key, p in dz.PRESETS.items()}}
HOOK_DUR = {"Hết cảnh đầu": "clip1", "3 giây": "3", "4 giây": "4", "5 giây": "5"}  # tối đa hết cảnh đầu
# mốc tiến trình theo log của hook_merge.py
STAGES = [("Đo tốc độ nói", 5, "Đo tốc độ nói từng clip..."), ("1/3 Ghép clip", 15, "Ghép + cắt + tăng tốc clip..."),
          ("2/3 Tách người", 35, "Tách người mẫu khỏi nền..."), ("Phân tích clip", 75, "Thiết kế chữ..."),
          ("3/3 Xếp lớp", 82, "Xuất video..."), ("Ảnh cover", 97, "Xuất ảnh cover...")]


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def python_exe() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable.replace("pythonw", "python")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


# Bảng màu: nền kem nhạt, thẻ trắng, 1 màu nhấn duy nhất
BG, CARD, BORDER = "#F4F2EF", "#FFFFFF", "#E6E1DB"
TEXT, MUTED = "#2B2622", "#8C847D"
ACCENT, ACCENT_DARK, ACCENT_SOFT = "#C2553A", "#A6452D", "#F7E4DD"
FONT = "Segoe UI"
PREVIEW_W, PREVIEW_H = 200, 356  # khung xem trước ảnh cover 9:16


class App(tk.Tk):
    def __init__(self, initial: list[str]):
        if os.name == "nt":  # chữ sắc nét trên màn hình có phóng to (DPI)
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        super().__init__()
        self.title("Video Hook Merger")
        self.configure(bg=BG)
        self.minsize(860, 640)
        self.clips: list[Path] = []
        self.proc: subprocess.Popen | None = None
        self.out_auto = True  # nơi lưu tự đổi theo clip, trừ khi người dùng tự chọn
        self.cover_img = None
        st = load_settings()
        self._style()

        # ---------- đầu trang ----------
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(head, text="Video Hook Merger", bg=BG, fg=TEXT, font=(FONT, 17, "bold")).pack(side="left")
        try:
            ver = "v" + updater.local_version()
        except Exception:
            ver = ""
        tk.Label(head, text=ver, bg=BG, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=(8, 0), pady=(6, 0))
        self.update_btn = ttk.Button(head, text="⟳  Cập nhật", style="Link.TButton", command=self.update_app)
        self.update_btn.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="ns", padx=(18, 0))

        # ---------- 1. Clip ----------
        c1 = self._card(left, "1", "Clip", "ghép theo thứ tự")
        acts = tk.Frame(c1.head, bg=CARD)
        acts.pack(side="right")
        ttk.Button(acts, text="+ Thêm clip", style="Soft.TButton", command=self.add_clips).pack(side="left")
        ttk.Button(acts, text="Thư mục…", style="CardLink.TButton", command=self.add_folder).pack(side="left", padx=(6, 0))
        self.listbox = tk.Listbox(c1.body, height=3, font=(FONT, 10), activestyle="none", bd=0, relief="flat",
                                  highlightthickness=0, bg="#FAF8F6", fg=TEXT, selectbackground=ACCENT_SOFT,
                                  selectforeground=TEXT)
        self.listbox.pack(fill="x", ipady=4)
        tools = tk.Frame(c1.body, bg=CARD)
        tools.pack(fill="x", pady=(6, 0))
        for txt, cmd in (("▲ Lên", lambda: self.move(-1)), ("▼ Xuống", lambda: self.move(1)),
                         ("✕ Xoá", self.remove), ("Xoá hết", self.clear)):
            ttk.Button(tools, text=txt, style="Mini.TButton", command=cmd).pack(side="left", padx=(0, 4))

        # ---------- 2. Hook ----------
        c2 = self._card(left, "2", "Câu hook")
        self.hook = tk.StringVar()
        ttk.Entry(c2.body, textvariable=self.hook, font=(FONT, 12), style="Big.TEntry").pack(fill="x", ipady=3)
        tk.Label(c2.body, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", justify="left",
                 text="Để trống: tự lấy từ tên file b1…   ·   dấu | để chia dòng   ·   *chữ* để tô màu").pack(
            fill="x", pady=(6, 0))

        # ---------- 3. Tuỳ chọn ----------
        c3 = self._card(left, "3", "Tuỳ chọn")
        row = tk.Frame(c3.body, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Tốc độ", bg=CARD, fg=TEXT, font=(FONT, 10)).pack(side="left")
        self.speed = tk.StringVar(value=str(st.get("speed", "1.15")))
        ttk.Spinbox(row, from_=0.5, to=2.0, increment=0.05, textvariable=self.speed, width=5,
                    font=(FONT, 10)).pack(side="left", padx=(8, 18))
        tk.Label(row, text="Phong cách chữ", bg=CARD, fg=TEXT, font=(FONT, 10)).pack(side="left")
        self.style_var = tk.StringVar(value=st.get("style", STYLE_AUTO) if st.get("style") in STYLES else STYLE_AUTO)
        ttk.Combobox(row, textvariable=self.style_var, values=list(STYLES), state="readonly",
                     width=30, font=(FONT, 10)).pack(side="left", padx=(8, 0), fill="x", expand=True)
        row2 = tk.Frame(c3.body, bg=CARD)
        row2.pack(fill="x", pady=(10, 0))
        self.sync = tk.BooleanVar(value=st.get("sync", True))
        self.trim = tk.BooleanVar(value=st.get("trim", True))
        self._toggle(row2, "Đồng bộ tốc độ nói", self.sync).pack(side="left")
        self._toggle(row2, "Cắt khoảng lặng", self.trim).pack(side="left", padx=(20, 0))
        self.adv_btn = ttk.Button(row2, text="Nâng cao ▸", style="CardLink.TButton", command=self.toggle_advanced)
        self.adv_btn.pack(side="right")
        # phần nâng cao (ẩn mặc định)
        self.adv = tk.Frame(c3.body, bg=CARD)
        a1 = tk.Frame(self.adv, bg=CARD)
        a1.pack(fill="x", pady=(10, 0))
        tk.Label(a1, text="Hiện chữ", bg=CARD, fg=TEXT, font=(FONT, 10), width=8, anchor="w").pack(side="left")
        self.dur = tk.StringVar(value=st.get("dur", "Hết cảnh đầu") if st.get("dur") in HOOK_DUR else "Hết cảnh đầu")
        ttk.Combobox(a1, textvariable=self.dur, values=list(HOOK_DUR), state="readonly", width=14,
                     font=(FONT, 10)).pack(side="left")
        a2 = tk.Frame(self.adv, bg=CARD)
        a2.pack(fill="x", pady=(8, 0))
        tk.Label(a2, text="Lưu vào", bg=CARD, fg=TEXT, font=(FONT, 10), width=8, anchor="w").pack(side="left")
        self.out = tk.StringVar()
        ttk.Entry(a2, textvariable=self.out, font=(FONT, 9)).pack(side="left", fill="x", expand=True)
        ttk.Button(a2, text="Đổi…", style="CardLink.TButton", command=self.pick_out).pack(side="left", padx=(6, 0))

        # ---------- chạy ----------
        run = tk.Frame(left, bg=BG)
        run.pack(fill="x", pady=(4, 0))
        top_run = tk.Frame(run, bg=BG)
        top_run.pack(fill="x")
        self.run_btn = ttk.Button(top_run, text="▶   Ghép video", style="Primary.TButton", command=self.start)
        self.run_btn.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ttk.Button(top_run, text="Huỷ", style="Link.TButton", command=self.cancel)
        self.bar = ttk.Progressbar(run, maximum=100, style="Accent.Horizontal.TProgressbar")
        srow = tk.Frame(run, bg=BG)
        srow.pack(fill="x", pady=(8, 0))
        self.srow = srow
        self.status = tk.Label(srow, text="Chọn clip rồi bấm Ghép video.", bg=BG, fg=MUTED, font=(FONT, 10),
                               anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.log_btn = ttk.Button(srow, text="Chi tiết ▸", style="Link.TButton", command=self.toggle_log)
        self.log_btn.pack(side="right")
        self.log = tk.Text(run, height=8, font=("Consolas", 9), wrap="word", state="disabled", bd=0,
                           bg="#FAF8F6", fg="#4A433E", highlightthickness=1, highlightbackground=BORDER,
                           padx=8, pady=6)

        # ---------- kết quả (cột phải) ----------
        pc = tk.Frame(right, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        pc.pack(fill="y", expand=True)
        tk.Label(pc, text="Kết quả", bg=CARD, fg=TEXT, font=(FONT, 11, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 8))
        box = tk.Frame(pc, bg="#F1EEEA", width=PREVIEW_W, height=PREVIEW_H)
        box.pack(padx=16)
        box.pack_propagate(False)
        self.cover = tk.Label(box, text="Ảnh cover\nsẽ hiện ở đây", bg="#F1EEEA", fg=MUTED, font=(FONT, 10),
                              justify="center")
        self.cover.pack(fill="both", expand=True)
        self.result_btns = tk.Frame(pc, bg=CARD)
        self.result_btns.pack(fill="x", padx=16, pady=(12, 16))
        self.open_btn = ttk.Button(self.result_btns, text="Mở video", style="Soft.TButton", command=self.open_video,
                                   state="disabled")
        self.open_btn.pack(fill="x")
        self.folder_btn = ttk.Button(self.result_btns, text="Mở thư mục", style="CardLink.TButton",
                                     command=self.open_folder, state="disabled")
        self.folder_btn.pack(fill="x", pady=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh()
        if initial:
            self.add_paths([Path(p) for p in initial])

    # ---------- giao diện ----------
    def _style(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=CARD, foreground=TEXT, font=(FONT, 10), bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER, focuscolor=ACCENT_SOFT)
        st.configure("Primary.TButton", background=ACCENT, foreground="white", font=(FONT, 12, "bold"),
                     padding=(16, 12), borderwidth=0)
        st.map("Primary.TButton", background=[("disabled", "#D9B3A8"), ("active", ACCENT_DARK)],
               foreground=[("disabled", "white")])
        st.configure("Soft.TButton", background=ACCENT_SOFT, foreground=ACCENT_DARK, font=(FONT, 10, "bold"),
                     padding=(12, 6), borderwidth=0)
        st.map("Soft.TButton", background=[("disabled", "#F1EEEA"), ("active", "#F0D3C8")],
               foreground=[("disabled", MUTED)])
        for name, bg in (("Link.TButton", BG), ("CardLink.TButton", CARD)):
            st.configure(name, background=bg, foreground=ACCENT_DARK, font=(FONT, 10), padding=(6, 4),
                         borderwidth=0)
            st.map(name, background=[("active", ACCENT_SOFT)], foreground=[("disabled", MUTED)])
        st.configure("Mini.TButton", background=CARD, foreground=MUTED, font=(FONT, 9), padding=(8, 3),
                     borderwidth=1, bordercolor=BORDER)
        st.map("Mini.TButton", background=[("active", "#F4F1ED")], foreground=[("active", TEXT)])
        st.configure("TEntry", fieldbackground="#FFFFFF", padding=6)
        st.configure("Big.TEntry", padding=(8, 6))
        st.configure("TCombobox", fieldbackground="#FFFFFF", padding=4, arrowsize=12, background=CARD,
                     arrowcolor=MUTED)
        st.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")], selectbackground=[("readonly", "#FFFFFF")],
               selectforeground=[("readonly", TEXT)])
        st.configure("TSpinbox", fieldbackground="#FFFFFF", padding=4, arrowsize=10, background=CARD,
                     arrowcolor=MUTED)
        st.configure("TCheckbutton", background=CARD, font=(FONT, 10))
        st.map("TCheckbutton", background=[("active", CARD)], indicatorcolor=[("selected", ACCENT)])
        st.configure("Accent.Horizontal.TProgressbar", troughcolor="#ECE7E1", background=ACCENT, thickness=4,
                     borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)

    def _card(self, parent, num: str, title: str, sub: str = ""):
        """Thẻ trắng có tiêu đề nhỏ; trả về frame có .head và .body."""
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 12))
        card.head = tk.Frame(card, bg=CARD)
        card.head.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(card.head, text=num, bg=ACCENT_SOFT, fg=ACCENT_DARK, font=(FONT, 9, "bold"), width=2).pack(side="left")
        tk.Label(card.head, text=title, bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(side="left", padx=(8, 0))
        if sub:
            tk.Label(card.head, text=sub, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(8, 0), pady=(2, 0))
        card.body = tk.Frame(card, bg=CARD)
        card.body.pack(fill="x", padx=16, pady=(0, 14))
        return card

    def _toggle(self, parent, text: str, var: tk.BooleanVar) -> tk.Frame:
        """Ô tick gọn: ☑ màu nhấn khi bật, ☐ xám khi tắt; bấm vào chữ cũng được."""
        f = tk.Frame(parent, bg=CARD, cursor="hand2")
        box = tk.Label(f, bg=CARD, font=(FONT, 13), cursor="hand2")
        box.pack(side="left")
        tk.Label(f, text=text, bg=CARD, fg=TEXT, font=(FONT, 10), cursor="hand2").pack(side="left", padx=(4, 0))

        def paint(*_):
            box.config(text="☑" if var.get() else "☐", fg=ACCENT if var.get() else MUTED)
        for w in (f, *f.winfo_children()):
            w.bind("<Button-1>", lambda _e: var.set(not var.get()))
        var.trace_add("write", paint)
        paint()
        return f

    def toggle_advanced(self) -> None:
        if self.adv.winfo_ismapped():
            self.adv.pack_forget()
            self.adv_btn.config(text="Nâng cao ▸")
        else:
            self.adv.pack(fill="x")
            self.adv_btn.config(text="Nâng cao ▾")

    def toggle_log(self) -> None:
        if self.log.winfo_ismapped():
            self.log.pack_forget()
            self.log_btn.config(text="Chi tiết ▸")
        else:
            self.log.pack(fill="both", expand=True, pady=(8, 0))
            self.log_btn.config(text="Chi tiết ▾")

    # ---------- clip ----------
    def add_paths(self, paths: list[Path]) -> None:
        for p in paths:
            if p.is_dir():
                self.clips += sorted((f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT
                                      and not f.stem.endswith("_hook")), key=natural_key)
            elif p.suffix.lower() in VIDEO_EXT:
                self.clips.append(p)
        self.refresh()

    def add_clips(self) -> None:
        files = filedialog.askopenfilenames(title="Chọn clip (giữ Ctrl để chọn nhiều)",
                                            filetypes=[("Video", " ".join(f"*{e}" for e in VIDEO_EXT))])
        self.add_paths(sorted((Path(f) for f in files), key=natural_key))

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Chọn thư mục chứa clip")
        if d:
            self.add_paths([Path(d)])

    def move(self, step: int) -> None:
        sel = self.listbox.curselection()
        if not sel or not self.clips:
            return
        i, j = sel[0], sel[0] + step
        if 0 <= j < len(self.clips):
            self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
            self.refresh()
            self.listbox.selection_set(j)

    def remove(self) -> None:
        if not self.clips:
            return
        for i in reversed(self.listbox.curselection()):
            del self.clips[i]
        self.refresh()

    def clear(self) -> None:
        self.clips.clear()
        self.refresh()

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        if not self.clips:  # dòng gợi ý khi chưa có clip
            self.listbox.insert("end", "   Chưa có clip — bấm  + Thêm clip  hoặc  Thư mục…")
            self.listbox.itemconfig(0, fg=MUTED, selectbackground="#FAF8F6", selectforeground=MUTED)
        for i, c in enumerate(self.clips, 1):
            self.listbox.insert("end", f"   {i}.   {c.name}")
        if self.clips and self.out_auto:  # lưu ngay trong thư mục chứa clip, không trùng tên file cũ
            folder = self.clips[0].parent
            out, k = folder / f"{folder.name}_hook.mp4", 2
            while out.exists():
                out, k = folder / f"{folder.name}_hook_{k}.mp4", k + 1
            self.out.set(str(out))

    def pick_out(self) -> None:
        f = filedialog.asksaveasfilename(title="Lưu video", defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")], initialfile=Path(self.out.get() or "video_hook.mp4").name)
        if f:
            self.out.set(f)
            self.out_auto = False

    # ---------- chạy ----------
    def start(self) -> None:
        if not self.clips:
            messagebox.showwarning("Thiếu clip", "Hãy chọn clip trước (nút Thêm clip… hoặc Chọn thư mục…).")
            return
        try:
            speed = float(self.speed.get().replace(",", "."))
            assert 0.5 <= speed <= 2.0
        except (ValueError, AssertionError):
            messagebox.showwarning("Tốc độ không hợp lệ", "Tốc độ phải là số từ 0.5 đến 2.0, ví dụ 1.15")
            return
        out = Path(self.out.get().strip() or self.clips[0].parent / "video_hook.mp4")
        if out.suffix.lower() != ".mp4":
            out = out.with_suffix(".mp4")
        if out.exists() and not messagebox.askyesno("Đã có file", f"{out.name} đã tồn tại. Ghi đè?"):
            return
        save_settings({"speed": speed, "sync": self.sync.get(), "trim": self.trim.get(),
                       "style": self.style_var.get(), "dur": self.dur.get()})

        cmd = [python_exe(), "-u", str(ROOT / "hook_merge.py"), *map(str, self.clips), "-o", str(out),
               "--speed", str(speed), "--hook-dur", HOOK_DUR[self.dur.get()]]
        if self.hook.get().strip():
            cmd += ["--hook", self.hook.get().strip()]
        if STYLES[self.style_var.get()]:
            cmd += ["--style", STYLES[self.style_var.get()]]
        if not self.sync.get():
            cmd.append("--no-sync-speed")
        if not self.trim.get():
            cmd.append("--no-trim")

        self.result = out
        self.set_log("")
        self.bar["value"] = 1
        self.status.config(text="Đang bắt đầu...")
        self.run_btn.config(state="disabled", text="Đang ghép…")
        self.cancel_btn.pack(side="left", padx=(10, 0))  # nút Huỷ chỉ hiện khi đang ghép
        if not self.bar.winfo_ismapped():
            self.bar.pack(fill="x", pady=(12, 0), before=self.srow)
        self.open_btn.config(state="disabled")
        self.folder_btn.config(state="disabled")
        self.status.config(fg=TEXT)
        self.cover.config(image="", text="Đang xử lý…")
        threading.Thread(target=self.worker, args=(cmd,), daemon=True).start()

    def worker(self, cmd: list[str]) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # không bật cửa sổ đen
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                         creationflags=flags, cwd=str(ROOT))
        except OSError as e:
            self.after(0, self.finish, False, f"Không chạy được: {e}. Hãy bấm Setup.bat.")
            return
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self.after(0, self.on_line, line)
        code = self.proc.wait()
        self.after(0, self.finish, code == 0, None)

    def on_line(self, line: str) -> None:
        m = re.match(r"Tách nền: (\d+)/(\d+)", line)
        if m:  # tiến trình tách nền 35% -> 75%
            a, b = int(m.group(1)), int(m.group(2))
            self.bar["value"] = 35 + 40 * a / max(1, b)
            self.status.config(text=f"Tách người mẫu khỏi nền... {a}/{b} frame")
            return
        if line.startswith("frame=") or line.startswith("size="):
            return  # thanh tiến trình của ffmpeg
        for key, pct, text in STAGES:
            if line.startswith(key) or line.lstrip().startswith(key):
                self.bar["value"] = max(self.bar["value"], pct)
                self.status.config(text=text)
        self.append_log(line)

    def finish(self, ok: bool, err: str | None) -> None:
        self.proc = None
        self.run_btn.config(state="normal", text="▶   Ghép video")
        self.cancel_btn.pack_forget()
        if ok and self.result.exists():
            self.bar["value"] = 100
            self.status.config(text=f"✓  Xong: {self.result.name}", fg="#3C7A4B")
            self.open_btn.config(state="normal")
            self.folder_btn.config(state="normal")
            self.show_cover(self.result.with_suffix(".cover.jpg"))
        else:
            self.status.config(text=err or "Có lỗi — bấm Chi tiết ▸ để xem.", fg=ACCENT_DARK)
            self.cover.config(image="", text="Chưa có kết quả")
            if not self.log.winfo_ismapped():
                self.toggle_log()
            if err:
                self.append_log(err)

    def show_cover(self, path: Path) -> None:
        try:
            from PIL import Image, ImageTk

            img = Image.open(path)
            img.thumbnail((PREVIEW_W, PREVIEW_H))
            self.cover_img = ImageTk.PhotoImage(img)
            self.cover.config(image=self.cover_img, text="")
        except Exception:
            self.cover.config(text="(không xem trước được ảnh cover)")

    def cancel(self) -> None:
        if self.proc and messagebox.askyesno("Huỷ", "Dừng ghép video?"):
            self.cancel_now()
            self.status.config(text="Đã huỷ.", fg=MUTED)

    def on_close(self) -> None:
        if self.proc and not messagebox.askyesno("Đang ghép", "Video đang được ghép. Thoát và huỷ?"):
            return
        if self.proc:
            self.cancel_now()
        self.destroy()

    def cancel_now(self) -> None:
        if os.name == "nt":  # dừng cả ffmpeg con
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.proc.kill()

    # ---------- cập nhật từ GitHub ----------
    def update_app(self) -> None:
        if self.proc:
            messagebox.showinfo("Đang ghép", "Chờ ghép video xong rồi hãy cập nhật.")
            return
        token = updater.read_token()
        if not token:
            token = simpledialog.askstring("Nhập GitHub token (1 lần)",
                                           updater.TOKEN_HELP + "\n\nDán token vào đây:", show="*", parent=self)
            if not token or not token.strip():
                return
            updater.save_token(token)
        self.update_btn.config(state="disabled", text="Đang kiểm tra…")
        threading.Thread(target=self._check_update, args=(token.strip(),), daemon=True).start()

    def _check_update(self, token: str) -> None:
        try:
            cur, new, newer = updater.check(token)
            self.after(0, self._ask_update, token, cur, new, newer)
        except updater.UpdateError as e:
            self.after(0, self._update_failed, str(e))

    def _ask_update(self, token: str, cur: str, new: str, newer: bool) -> None:
        if not newer:
            self._update_done()
            messagebox.showinfo("Cập nhật", f"Bạn đang dùng bản mới nhất (v{cur}).")
            return
        if not messagebox.askyesno("Có bản mới", f"Đang dùng v{cur}, trên GitHub có v{new}.\n"
                                   "Cập nhật ngay? App sẽ tự mở lại sau khi xong."):
            self._update_done()
            return
        self.update_btn.config(text="Đang cập nhật…")
        self.status.config(text=f"Đang cập nhật lên v{new}…")

        def work():
            try:
                log = lambda m: self.after(0, self.append_log, m)
                if updater.apply_update(token, log):
                    updater.install_deps(log)
                self.after(0, self._restart, new)
            except updater.UpdateError as e:
                self.after(0, self._update_failed, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _update_failed(self, msg: str) -> None:
        self._update_done()
        if "Token" in msg or "quyền" in msg:
            updater.forget_token()  # lần sau hỏi lại token
            msg += "\nLần bấm Cập nhật sau sẽ hỏi lại token."
        messagebox.showerror("Chưa cập nhật được", msg)

    def _update_done(self) -> None:
        self.update_btn.config(state="normal", text="⟳  Cập nhật")

    def _restart(self, new: str) -> None:
        messagebox.showinfo("Đã cập nhật", f"Đã cập nhật lên v{new}. App sẽ mở lại.")
        subprocess.Popen([sys.executable, str(ROOT / "gui.py")], cwd=str(ROOT))
        self.destroy()

    # ---------- tiện ích ----------
    def set_log(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.config(state="disabled")

    def append_log(self, line: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def open_video(self) -> None:
        os.startfile(self.result) if os.name == "nt" else subprocess.run(["open", str(self.result)])

    def open_folder(self) -> None:
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", str(self.result)])
        else:
            subprocess.run(["open", str(self.result.parent)])


if __name__ == "__main__":
    App(sys.argv[1:]).mainloop()
