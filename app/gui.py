"""Giao diện Video Hook Merger (CustomTkinter: góc bo tròn, nền tối, gọn 1 cột).

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
from tkinter import filedialog, messagebox, simpledialog

ROOT = Path(__file__).resolve().parent


def _ensure_customtkinter():
    """Máy vừa bấm Cập nhật mà chưa cài được thư viện giao diện: tự cài (~1 MB), không được thì báo rõ
    (app chạy bằng pythonw nên nếu không báo, cửa sổ sẽ tắt im lặng)."""
    try:
        import customtkinter  # noqa: F401
        return
    except ImportError:
        pass
    py = Path(sys.executable)
    py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists() else py
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    res = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "customtkinter>=5.2,<7"],
                         capture_output=True, creationflags=flags)
    if res.returncode != 0:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Thiếu thư viện giao diện",
                             "Chưa cài được thư viện giao diện (customtkinter), có thể do mất mạng.\n"
                             "Hãy kiểm tra mạng rồi bấm Setup.bat trong thư mục tool.")
        sys.exit(1)


_ensure_customtkinter()
import customtkinter as ctk  # noqa: E402
sys.path.insert(0, str(ROOT))
import design as dz  # noqa: E402  (chỉ lấy tên phong cách, không nạp torch)
import updater  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SETTINGS = ROOT / ".gui_settings.json"
STYLE_AUTO = "Tự động"
STYLES = {STYLE_AUTO: None, **{p.label: key for key, p in dz.PRESETS.items()}}
HOOK_DUR = {"Hết cảnh đầu": "clip1", "3 giây": "3", "4 giây": "4", "5 giây": "5"}  # tối đa hết cảnh đầu
SPEEDS = ["1.0", "1.1", "1.15", "1.2", "1.3"]
AUTO_CHECK_MS = 3 * 3600 * 1000  # app để mở lâu: kiểm tra bản mới mỗi 3 tiếng
# mốc tiến trình (0-1) theo log của hook_merge.py
STAGES = [("Đo tốc độ nói", 0.05, "Đo tốc độ nói từng clip…"), ("1/3 Ghép clip", 0.15, "Ghép + cắt + tăng tốc…"),
          ("2/3 Tách người", 0.35, "Tách người mẫu khỏi nền…"), ("Phân tích clip", 0.78, "Thiết kế chữ…"),
          ("3/3 Xếp lớp", 0.85, "Xuất video…")]

# Tone tối + 1 màu nhấn tím
BG, CARD, FIELD = "#15161B", "#1E2028", "#272A35"
TEXT, MUTED = "#ECEDF2", "#8A8D9A"
ACCENT, ACCENT_HOVER = "#7C5CFF", "#6848F0"
OK_COLOR, ERR_COLOR = "#4ADE80", "#F87171"
FONT = "Segoe UI"
R = 12  # bán kính bo góc


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


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


class App(ctk.CTk):
    def __init__(self, initial: list[str]):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("Video Hook Merger")
        self.minsize(540, 0)  # cao theo nội dung: mở "Chi tiết" thì cửa sổ tự dài ra
        self.clips: list[Path] = []
        self.proc: subprocess.Popen | None = None
        self.out_auto = True  # nơi lưu tự đổi theo clip, trừ khi người dùng tự chọn
        self.result: Path | None = None
        st = load_settings()
        small = dict(height=30, corner_radius=8, font=font(12), fg_color=FIELD, hover_color="#323644",
                     text_color=TEXT)

        wrap = ctk.CTkFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=16)

        # ---------- đầu trang ----------
        head = ctk.CTkFrame(wrap, fg_color=BG)
        head.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(head, text="Video Hook Merger", font=font(19, "bold"), text_color=TEXT).pack(side="left")
        try:
            ver = "v" + updater.local_version()
        except Exception:
            ver = ""
        ctk.CTkLabel(head, text=ver, font=font(12), text_color=MUTED).pack(side="left", padx=(8, 0), pady=(4, 0))
        self.update_btn = ctk.CTkButton(head, text="⟳  Cập nhật", width=96, command=self.update_app, **small)
        self.update_btn.pack(side="right")
        self.banner = ctk.CTkFrame(wrap, fg_color=CARD, corner_radius=R, border_width=1, border_color=ACCENT)
        self.banner_label = ctk.CTkLabel(self.banner, text="", font=font(13, "bold"), text_color=TEXT)
        self.banner_label.pack(side="left", padx=(14, 0), pady=8)
        ctk.CTkButton(self.banner, text="✕", width=30, height=28, corner_radius=8, font=font(12),
                      fg_color="transparent", hover_color=FIELD, text_color=MUTED,
                      command=self.dismiss_banner).pack(side="right", padx=(0, 8))
        ctk.CTkButton(self.banner, text="Cập nhật", width=90, height=28, corner_radius=8, font=font(12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.update_app).pack(side="right", padx=6)
        self.banner_anchor = ctk.CTkFrame(wrap, fg_color=BG, height=0)  # mốc để chèn dải thông báo đúng chỗ
        self.banner_anchor.pack(fill="x")
        self.dismissed_version: str | None = None

        # ---------- clip ----------
        clip = self._card(wrap)
        ch = ctk.CTkFrame(clip, fg_color=CARD)
        ch.pack(fill="x")
        ctk.CTkLabel(ch, text="Clip", font=font(14, "bold"), text_color=TEXT).pack(side="left")
        self.count = ctk.CTkLabel(ch, text="", font=font(12), text_color=MUTED)
        self.count.pack(side="left", padx=(8, 0))
        ctk.CTkButton(ch, text="Thư mục", width=74, command=self.add_folder, **small).pack(side="right")
        ctk.CTkButton(ch, text="+ Thêm clip", width=96, height=30, corner_radius=8, font=font(12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.add_clips).pack(side="right", padx=6)
        for txt, cmd in (("✕", self.remove), ("↓", lambda: self.move(1)), ("↑", lambda: self.move(-1))):
            ctk.CTkButton(ch, text=txt, width=30, command=cmd, **small).pack(side="right", padx=(0, 4))
        box = ctk.CTkFrame(clip, fg_color=FIELD, corner_radius=10)
        box.pack(fill="x", pady=(10, 0))
        self.listbox = tk.Listbox(box, height=3, font=(FONT, 10), activestyle="none", bd=0, relief="flat",
                                  highlightthickness=0, bg=FIELD, fg=TEXT, selectbackground=ACCENT,
                                  selectforeground="white")
        self.listbox.pack(fill="x", padx=10, pady=8)

        # ---------- câu hook ----------
        # không gắn textvariable: CustomTkinter chỉ hiện chữ gợi ý khi ô nhập không gắn biến
        self.hook = ctk.CTkEntry(wrap, height=42, corner_radius=R, font=font(14), fg_color=CARD,
                                 border_width=0, text_color=TEXT, placeholder_text_color=MUTED,
                                 placeholder_text="Câu hook  ·  để trống = không có chữ  ·  | chia dòng  ·  "
                                                  "*chữ* tô màu")
        self.hook.pack(fill="x", pady=(10, 0))

        # ---------- tuỳ chọn ----------
        opt = self._card(wrap)
        r1 = ctk.CTkFrame(opt, fg_color=CARD)
        r1.pack(fill="x")
        ctk.CTkLabel(r1, text="Tốc độ", font=font(13), text_color=TEXT).pack(side="left")
        self.speed = ctk.StringVar(value=str(st.get("speed", "1.15")))
        ctk.CTkComboBox(r1, values=SPEEDS, variable=self.speed, width=78, height=30, corner_radius=8,
                        font=font(12), fg_color=FIELD, border_width=0, button_color=FIELD,
                        button_hover_color="#323644", dropdown_fg_color=FIELD).pack(side="left", padx=(8, 16))
        ctk.CTkLabel(r1, text="Chữ", font=font(13), text_color=TEXT).pack(side="left")
        self.style_var = ctk.StringVar(value=st.get("style", STYLE_AUTO) if st.get("style") in STYLES else STYLE_AUTO)
        ctk.CTkOptionMenu(r1, values=list(STYLES), variable=self.style_var, height=30, corner_radius=8,
                          font=font(12), fg_color=FIELD, button_color=FIELD, button_hover_color="#323644",
                          dropdown_fg_color=FIELD, dynamic_resizing=False).pack(
            side="left", padx=(8, 0), fill="x", expand=True)
        r2 = ctk.CTkFrame(opt, fg_color=CARD)
        r2.pack(fill="x", pady=(12, 0))
        self.sync = ctk.BooleanVar(value=st.get("sync", True))
        self.trim = ctk.BooleanVar(value=st.get("trim", True))
        sw = dict(font=font(12), text_color=TEXT, progress_color=ACCENT, button_color="#FFFFFF",
                  button_hover_color="#E6E6EE", fg_color=FIELD, switch_width=36, switch_height=18)
        ctk.CTkSwitch(r2, text="Đồng bộ tốc độ nói", variable=self.sync, **sw).pack(side="left")
        ctk.CTkSwitch(r2, text="Cắt khoảng lặng", variable=self.trim, **sw).pack(side="left", padx=(16, 0))
        self.adv_btn = ctk.CTkButton(r2, text="Nâng cao ▾", width=90, height=26, corner_radius=8, font=font(12),
                                     fg_color="transparent", hover_color=FIELD, text_color=MUTED,
                                     command=self.toggle_advanced)
        self.adv_btn.pack(side="right")
        self.adv = ctk.CTkFrame(opt, fg_color=CARD)  # ẩn mặc định
        a1 = ctk.CTkFrame(self.adv, fg_color=CARD)
        a1.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(a1, text="Hiện chữ", font=font(13), text_color=TEXT, width=64, anchor="w").pack(side="left")
        self.dur = ctk.StringVar(value=st.get("dur", "Hết cảnh đầu") if st.get("dur") in HOOK_DUR else "Hết cảnh đầu")
        ctk.CTkOptionMenu(a1, values=list(HOOK_DUR), variable=self.dur, width=140, height=30, corner_radius=8,
                          font=font(12), fg_color=FIELD, button_color=FIELD, button_hover_color="#323644",
                          dropdown_fg_color=FIELD).pack(side="left")
        a2 = ctk.CTkFrame(self.adv, fg_color=CARD)
        a2.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(a2, text="Lưu vào", font=font(13), text_color=TEXT, width=64, anchor="w").pack(side="left")
        self.out = ctk.StringVar()
        ctk.CTkEntry(a2, textvariable=self.out, height=30, corner_radius=8, font=font(11), fg_color=FIELD,
                     border_width=0, text_color=TEXT).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(a2, text="…", width=34, command=self.pick_out, **small).pack(side="left", padx=(6, 0))

        # ---------- chạy ----------
        runrow = ctk.CTkFrame(wrap, fg_color=BG)
        runrow.pack(fill="x", pady=(14, 0))
        self.run_btn = ctk.CTkButton(runrow, text="Ghép video", height=46, corner_radius=R, font=font(15, "bold"),
                                     fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                                     text_color_disabled="#D8D0FF", command=self.start)
        self.run_btn.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ctk.CTkButton(runrow, text="Huỷ", width=70, height=46, corner_radius=R, font=font(13),
                                        fg_color=CARD, hover_color=FIELD, text_color=TEXT, command=self.cancel)
        self.prog_slot = ctk.CTkFrame(wrap, fg_color=BG, height=1)  # giữ chỗ cho thanh tiến trình
        self.prog_slot.pack(fill="x")
        self.bar = ctk.CTkProgressBar(self.prog_slot, height=6, corner_radius=3, progress_color=ACCENT,
                                      fg_color=CARD)
        self.bar.set(0)
        srow = ctk.CTkFrame(wrap, fg_color=BG)
        srow.pack(fill="x", pady=(8, 0))
        self.status = ctk.CTkLabel(srow, text="Chọn clip rồi bấm Ghép video.", font=font(12), text_color=MUTED,
                                   anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.log_btn = ctk.CTkButton(srow, text="Chi tiết", width=70, height=26, corner_radius=8, font=font(12),
                                     fg_color="transparent", hover_color=CARD, text_color=MUTED,
                                     command=self.toggle_log)
        self.log_btn.pack(side="right")
        self.done_row = ctk.CTkFrame(wrap, fg_color=BG)  # hiện khi ghép xong
        self.open_btn = ctk.CTkButton(self.done_row, text="▶  Mở video", height=36, corner_radius=10,
                                      font=font(13, "bold"), fg_color=CARD, hover_color=FIELD, text_color=TEXT,
                                      border_width=1, border_color=ACCENT, command=self.open_video)
        self.open_btn.pack(side="left", fill="x", expand=True)
        self.folder_btn = ctk.CTkButton(self.done_row, text="Mở thư mục", width=110, height=36, corner_radius=10,
                                        font=font(13), fg_color=CARD, hover_color=FIELD, text_color=TEXT,
                                        command=self.open_folder)
        self.folder_btn.pack(side="left", padx=(8, 0))
        self.log = ctk.CTkTextbox(wrap, height=150, corner_radius=R, font=ctk.CTkFont(family="Consolas", size=11),
                                  fg_color=CARD, text_color="#C9CBD6", border_width=0, state="disabled")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(2500, self.auto_check)  # tự kiểm tra bản mới khi mở app
        self.refresh()
        if initial:
            self.add_paths([Path(p) for p in initial])

    # ---------- giao diện ----------
    def _card(self, parent) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=R)
        card.pack(fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(card, fg_color=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        return inner

    def toggle_advanced(self) -> None:
        if self.adv.winfo_ismapped():
            self.adv.pack_forget()
            self.adv_btn.configure(text="Nâng cao ▾")
        else:
            self.adv.pack(fill="x")
            self.adv_btn.configure(text="Nâng cao ▴")

    def toggle_log(self) -> None:
        if self.log.winfo_ismapped():
            self.log.pack_forget()
        else:
            self.log.pack(fill="both", expand=True, pady=(8, 0))

    def _busy(self, busy: bool) -> None:
        if busy:
            self.run_btn.configure(state="disabled", text="Đang ghép…")
            self.cancel_btn.pack(side="left", padx=(8, 0))
            self.bar.pack(fill="x", pady=(12, 0))
            self.done_row.pack_forget()
        else:
            self.run_btn.configure(state="normal", text="Ghép video")
            self.cancel_btn.pack_forget()

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
        sel = self.listbox.curselection()
        if not sel:  # chưa chọn dòng nào: hỏi xoá hết
            if messagebox.askyesno("Xoá clip", "Xoá hết danh sách clip?"):
                self.clips.clear()
        else:
            for i in reversed(sel):
                del self.clips[i]
        self.refresh()

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        if not self.clips:  # dòng gợi ý khi chưa có clip
            self.listbox.insert("end", "Chưa có clip — bấm  + Thêm clip  hoặc  Thư mục")
            self.listbox.itemconfig(0, fg=MUTED, selectbackground=FIELD, selectforeground=MUTED)
        for i, c in enumerate(self.clips, 1):
            self.listbox.insert("end", f"{i}.  {c.name}")
        self.count.configure(text=f"{len(self.clips)} clip" if self.clips else "")
        if self.clips and self.out_auto:  # lưu ngay trong thư mục chứa clip, không trùng tên file cũ
            folder = self.clips[0].parent
            out, k = folder / f"{folder.name}_hook.mp4", 2
            while out.exists():
                out, k = folder / f"{folder.name}_hook_{k}.mp4", k + 1
            self.out.set(str(out))

    def pick_out(self) -> None:
        f = filedialog.asksaveasfilename(title="Lưu video", defaultextension=".mp4", filetypes=[("MP4", "*.mp4")],
                                         initialfile=Path(self.out.get() or "video_hook.mp4").name)
        if f:
            self.out.set(f)
            self.out_auto = False

    # ---------- chạy ----------
    def start(self) -> None:
        if not self.clips:
            messagebox.showwarning("Thiếu clip", "Hãy chọn clip trước (+ Thêm clip hoặc Thư mục).")
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
        self.bar.set(0.01)
        self.status.configure(text="Đang bắt đầu…", text_color=TEXT)
        self._busy(True)
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
        if m:  # tiến trình tách nền 35% -> 78%
            a, b = int(m.group(1)), int(m.group(2))
            self.bar.set(0.35 + 0.43 * a / max(1, b))
            self.status.configure(text=f"Tách người mẫu khỏi nền…  {a}/{b}")
            return
        if line.startswith("frame=") or line.startswith("size="):
            return  # thanh tiến trình của ffmpeg
        for key, frac, text in STAGES:
            if line.startswith(key) or line.lstrip().startswith(key):
                self.bar.set(max(self.bar.get(), frac))
                self.status.configure(text=text)
        self.append_log(line)

    def finish(self, ok: bool, err: str | None) -> None:
        self.proc = None
        self._busy(False)
        if ok and self.result and self.result.exists():
            self.bar.set(1)
            self.status.configure(text=f"✓  Xong: {self.result.name}", text_color=OK_COLOR)
            self.done_row.pack(fill="x", pady=(10, 0), before=self.log if self.log.winfo_ismapped() else None)
        else:
            self.status.configure(text=err or "Có lỗi — bấm Chi tiết để xem.", text_color=ERR_COLOR)
            if err:
                self.append_log(err)
            if not self.log.winfo_ismapped():
                self.toggle_log()

    def cancel(self) -> None:
        if self.proc and messagebox.askyesno("Huỷ", "Dừng ghép video?"):
            self.cancel_now()
            self.status.configure(text="Đã huỷ.", text_color=MUTED)

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

    # ---------- tự kiểm tra bản mới ----------
    def auto_check(self) -> None:
        """Kiểm tra bản mới trong nền: có thì hiện dải thông báo; lỗi mạng / chưa có token thì im lặng."""
        self.after(AUTO_CHECK_MS, self.auto_check)
        token = updater.read_token()
        if not token or self.proc:
            return

        def work():
            try:
                cur, new, newer = updater.check(token)
            except Exception:
                return  # không làm phiền khi mất mạng / token hết hạn (bấm Cập nhật sẽ báo rõ)
            if newer and new != self.dismissed_version:
                self.after(0, self.show_banner, new)
        threading.Thread(target=work, daemon=True).start()

    def show_banner(self, new: str) -> None:
        self.banner_label.configure(text=f"✦  Có bản mới v{new}")
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", pady=(0, 2), after=self.banner_anchor)
        self.update_btn.configure(text=f"⟳  v{new}", fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.banner_version = new

    def dismiss_banner(self) -> None:
        self.dismissed_version = getattr(self, "banner_version", None)  # không nhắc lại bản này
        self.banner.pack_forget()

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
        self.update_btn.configure(state="disabled", text="Đang kiểm tra…")
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
        self.update_btn.configure(text="Đang cập nhật…")
        self.status.configure(text=f"Đang cập nhật lên v{new}…", text_color=TEXT)

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
        self.update_btn.configure(state="normal", text="⟳  Cập nhật")

    def _restart(self, new: str) -> None:
        messagebox.showinfo("Đã cập nhật", f"Đã cập nhật lên v{new}. App sẽ mở lại.")
        subprocess.Popen([sys.executable, str(ROOT / "gui.py")], cwd=str(ROOT))
        self.destroy()

    # ---------- tiện ích ----------
    def set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.configure(state="disabled")

    def append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_video(self) -> None:
        os.startfile(self.result) if os.name == "nt" else subprocess.run(["open", str(self.result)])

    def open_folder(self) -> None:
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", str(self.result)])
        else:
            subprocess.run(["open", str(self.result.parent)])


if __name__ == "__main__":
    App(sys.argv[1:]).mainloop()
