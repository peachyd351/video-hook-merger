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
HOOK_DUR = {"Hết cảnh đầu": "clip1", "3 giây": "3", "4 giây": "4", "5 giây": "5"}
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


class App(tk.Tk):
    def __init__(self, initial: list[str]):
        super().__init__()
        self.title("Video Hook Merger - Ghép video + chữ hook")
        self.minsize(760, 640)
        self.clips: list[Path] = []
        self.proc: subprocess.Popen | None = None
        self.out_auto = True  # nơi lưu tự đổi theo clip, trừ khi người dùng tự chọn
        self.cover_img = None
        st = load_settings()

        style = ttk.Style(self)
        style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=8)
        style.configure("H.TLabel", font=("Segoe UI", 10, "bold"))
        pad = {"padx": 10, "pady": 4}

        # --- thanh trên cùng: phiên bản + cập nhật ---
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(8, 0))
        try:
            ver = "v" + updater.local_version()
        except Exception:
            ver = ""
        ttk.Label(top, text=f"Video Hook Merger {ver}", style="H.TLabel").pack(side="left")
        self.update_btn = ttk.Button(top, text="⟳ Cập nhật", command=self.update_app)
        self.update_btn.pack(side="right")

        # --- 1. Clip ---
        f1 = ttk.LabelFrame(self, text=" 1. Chọn clip (ghép theo thứ tự trong danh sách) ")
        f1.pack(fill="x", **pad)
        self.listbox = tk.Listbox(f1, height=4, font=("Segoe UI", 10), activestyle="none")
        self.listbox.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=6, pady=6)
        f1.columnconfigure(0, weight=1)
        for r, (txt, cmd) in enumerate([("Thêm clip…", self.add_clips), ("Chọn thư mục…", self.add_folder),
                                        ("▲ Lên", lambda: self.move(-1)), ("▼ Xuống", lambda: self.move(1))]):
            ttk.Button(f1, text=txt, command=cmd, width=14).grid(row=r, column=1, padx=6, pady=2, sticky="ew")
        ttk.Button(f1, text="Xoá", command=self.remove, width=14).grid(row=0, column=2, padx=(0, 6), pady=2)
        ttk.Button(f1, text="Xoá hết", command=self.clear, width=14).grid(row=1, column=2, padx=(0, 6), pady=2)

        # --- 2. Hook ---
        f2 = ttk.LabelFrame(self, text=" 2. Câu hook ")
        f2.pack(fill="x", **pad)
        self.hook = tk.StringVar()
        ttk.Entry(f2, textvariable=self.hook, font=("Segoe UI", 12)).pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(f2, foreground="#666", text="Để trống = tự lấy từ hook.txt / tên file b1… / kho câu mẫu.  Câu ngắn tự thành 1 dòng.\n"
                  "Dấu | để tự chia 2 dòng · *dấu sao* để chọn chữ tô màu, vd:  Hẹn hò cuối tuần | Diện ngay *set này*",
                  justify="left").pack(
            anchor="w", padx=6, pady=(0, 6))

        # --- 3. Tuỳ chọn ---
        f3 = ttk.LabelFrame(self, text=" 3. Tuỳ chọn ")
        f3.pack(fill="x", **pad)
        ttk.Label(f3, text="Tốc độ:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.speed = tk.StringVar(value=str(st.get("speed", "1.15")))
        ttk.Spinbox(f3, from_=0.5, to=2.0, increment=0.05, textvariable=self.speed, width=7,
                    font=("Segoe UI", 11)).grid(row=0, column=1, sticky="w")
        ttk.Label(f3, foreground="#666", text="1.0 = giữ nguyên · 1.1 = như video mẫu · 1.15 = mặc định").grid(
            row=0, column=2, columnspan=2, sticky="w", padx=6)
        self.sync = tk.BooleanVar(value=st.get("sync", True))
        self.trim = tk.BooleanVar(value=st.get("trim", True))
        ttk.Checkbutton(f3, text="Đồng bộ tốc độ nói giữa các clip", variable=self.sync).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(f3, text="Cắt khoảng lặng + jump cut", variable=self.trim).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Label(f3, text="Phong cách chữ:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.style_var = tk.StringVar(value=st.get("style", STYLE_AUTO) if st.get("style") in STYLES else STYLE_AUTO)
        ttk.Combobox(f3, textvariable=self.style_var, values=list(STYLES), state="readonly", width=38).grid(
            row=2, column=1, columnspan=2, sticky="w")
        ttk.Label(f3, text="Hiện chữ:").grid(row=3, column=0, sticky="w", padx=6, pady=(4, 8))
        self.dur = tk.StringVar(value=st.get("dur", "Hết cảnh đầu") if st.get("dur") in HOOK_DUR else "Hết cảnh đầu")
        ttk.Combobox(f3, textvariable=self.dur, values=list(HOOK_DUR), state="readonly", width=16).grid(
            row=3, column=1, columnspan=2, sticky="w", pady=(4, 8))

        # --- 4. Lưu ---
        f4 = ttk.LabelFrame(self, text=" 4. Lưu video vào ")
        f4.pack(fill="x", **pad)
        self.out = tk.StringVar()
        ttk.Entry(f4, textvariable=self.out, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True,
                                                                        padx=6, pady=6)
        ttk.Button(f4, text="Chọn…", command=self.pick_out).pack(side="left", padx=6)

        # --- 5. Chạy + kết quả ---
        f5 = ttk.Frame(self)
        f5.pack(fill="both", expand=True, **pad)
        left = ttk.Frame(f5)
        left.pack(side="left", fill="both", expand=True)
        row = ttk.Frame(left)
        row.pack(fill="x")
        self.run_btn = ttk.Button(row, text="▶  GHÉP VIDEO", style="Big.TButton", command=self.start)
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(row, text="Huỷ", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.status = ttk.Label(left, text="Chọn clip rồi bấm GHÉP VIDEO.", style="H.TLabel")
        self.status.pack(anchor="w", pady=(8, 2))
        self.bar = ttk.Progressbar(left, maximum=100)
        self.bar.pack(fill="x")
        self.log = tk.Text(left, height=9, font=("Consolas", 9), wrap="word", state="disabled", bg="#f7f7f7")
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        right = ttk.Frame(f5, width=190)
        right.pack(side="left", fill="y", padx=(10, 0))
        self.cover = ttk.Label(right, text="Ảnh cover\nsẽ hiện ở đây", anchor="center", justify="center",
                               relief="groove", width=24)
        self.cover.pack(fill="both", expand=True)
        self.open_btn = ttk.Button(right, text="Mở video", command=self.open_video, state="disabled")
        self.open_btn.pack(fill="x", pady=(6, 2))
        self.folder_btn = ttk.Button(right, text="Mở thư mục", command=self.open_folder, state="disabled")
        self.folder_btn.pack(fill="x")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if initial:
            self.add_paths([Path(p) for p in initial])

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
        if not sel:
            return
        i, j = sel[0], sel[0] + step
        if 0 <= j < len(self.clips):
            self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
            self.refresh()
            self.listbox.selection_set(j)

    def remove(self) -> None:
        for i in reversed(self.listbox.curselection()):
            del self.clips[i]
        self.refresh()

    def clear(self) -> None:
        self.clips.clear()
        self.refresh()

    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        for i, c in enumerate(self.clips, 1):
            self.listbox.insert("end", f"  {i}.  {c.name}")
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
        self.run_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.open_btn.config(state="disabled")
        self.folder_btn.config(state="disabled")
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
        self.run_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        if ok and self.result.exists():
            self.bar["value"] = 100
            self.status.config(text=f"XONG!  {self.result.name}")
            self.open_btn.config(state="normal")
            self.folder_btn.config(state="normal")
            self.show_cover(self.result.with_suffix(".cover.jpg"))
        else:
            self.status.config(text="Có lỗi, xem nhật ký bên dưới." if not err else err)
            self.cover.config(image="", text="Chưa có kết quả")
            if err:
                self.append_log(err)

    def show_cover(self, path: Path) -> None:
        try:
            from PIL import Image, ImageTk

            img = Image.open(path)
            img.thumbnail((180, 320))
            self.cover_img = ImageTk.PhotoImage(img)
            self.cover.config(image=self.cover_img, text="")
        except Exception:
            self.cover.config(text="(không xem trước được ảnh cover)")

    def cancel(self) -> None:
        if self.proc and messagebox.askyesno("Huỷ", "Dừng ghép video?"):
            self.cancel_now()
            self.status.config(text="Đã huỷ.")

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
        self.update_btn.config(state="normal", text="⟳ Cập nhật")

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
