"""Tự cập nhật Video Hook Merger từ repo GitHub (private).

- Phiên bản mới = số "version" trong app/PACKAGE.json trên nhánh main lớn hơn bản đang cài.
- Chỉ chép đè code/font/model từ GitHub; giữ nguyên thư viện đã cài (.venv), model Whisper (.cache)
  và cài đặt của người dùng. requirements.txt đổi thì tự cài thêm thư viện.
- Repo private: mỗi máy nhập 1 lần GitHub token chỉ-đọc; token lưu trong %APPDATA%, không nằm
  trong thư mục app (chép app cho người khác thì token không đi theo).

  python updater.py --check      # chỉ xem có bản mới không
  python updater.py --apply      # cập nhật (không hỏi lại)
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent
TOP = APP.parent
CONFIG = APP / "update.json"  # {"repo": "owner/name", "branch": "main"}
TOKEN_FILE = Path(os.environ.get("APPDATA") or Path.home()) / "VideoHookMerger" / "github_token.txt"
KEEP = {".venv", ".cache", "__pycache__", ".git", "setup.log", ".gui_settings.json", ".hook_history.json"}
TOKEN_HELP = ("Tạo token (1 lần): github.com → ảnh đại diện → Settings → Developer settings → "
              "Personal access tokens → Fine-grained tokens → Generate new token. "
              "Repository access: chỉ chọn repo của tool. Permissions → Contents: Read-only.")


class UpdateError(RuntimeError):
    pass


def config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if not cfg.get("repo") or "/" not in cfg["repo"]:
        raise UpdateError("Chưa cấu hình repo GitHub trong app/update.json.")
    cfg.setdefault("branch", "main")
    return cfg


def read_token() -> str | None:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip(), encoding="utf-8")


def forget_token() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.strip().lstrip("v").split(".") if x.isdigit())


def local_version() -> str:
    return json.loads((APP / "PACKAGE.json").read_text(encoding="utf-8"))["version"]


def _get(url: str, token: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "video-hook-merger-updater"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UpdateError("Token GitHub sai hoặc hết hạn.") from e
        if e.code == 404:
            raise UpdateError("Không thấy repo (sai tên repo, hoặc token chưa được cấp quyền đọc repo này).") from e
        raise UpdateError(f"GitHub báo lỗi {e.code}.") from e
    except urllib.error.URLError as e:
        raise UpdateError("Không kết nối được GitHub (kiểm tra mạng).") from e


def remote_version(token: str) -> str:
    cfg = config()
    raw = _get(f"https://api.github.com/repos/{cfg['repo']}/contents/app/PACKAGE.json?ref={cfg['branch']}", token)
    content = base64.b64decode(json.loads(raw)["content"])
    return json.loads(content)["version"]


def check(token: str) -> tuple[str, str, bool]:
    """(bản đang cài, bản trên GitHub, có bản mới?)"""
    cur, new = local_version(), remote_version(token)
    return cur, new, version_tuple(new) > version_tuple(cur)


def apply_update(token: str, log=print) -> bool:
    """Tải nhánh main và chép đè. Trả về True nếu requirements.txt đổi (cần cài thêm thư viện)."""
    cfg = config()
    log("Đang tải bản mới từ GitHub ...")
    data = _get(f"https://api.github.com/repos/{cfg['repo']}/zipball/{cfg['branch']}", token)
    old_req = (APP / "requirements.txt").read_bytes() if (APP / "requirements.txt").exists() else b""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        root = names[0].split("/", 1)[0] + "/"  # thư mục gốc "owner-repo-sha/"
        if not any(n == root + "app/hook_merge.py" for n in names):
            raise UpdateError("Bản trên GitHub không đúng cấu trúc (thiếu app/hook_merge.py), không cập nhật.")
        count = 0
        for n in names:
            rel = n[len(root):]
            parts = rel.split("/")
            if not rel or any(p in KEEP for p in parts):
                continue
            dest = TOP / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    log(f"Đã chép {count} file.")
    return (APP / "requirements.txt").read_bytes() != old_req


def install_deps(log=print) -> None:
    """Cài thêm thư viện mới (requirements.txt đổi). Dùng đúng Python của .venv."""
    log("Bản mới cần thêm thư viện, đang cài ...")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    res = subprocess.run([sys.executable, str(APP / "install.py"), "--yes", "--skip-verify"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    if res.returncode != 0:
        raise UpdateError("Cài thư viện cho bản mới chưa xong. Hãy bấm Setup.bat.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    token = read_token() or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Chưa có token. " + TOKEN_HELP)
        return 2
    try:
        cur, new, newer = check(token)
        print(f"Đang dùng v{cur}, trên GitHub v{new}" + (" -> có bản mới" if newer else " -> đã mới nhất"))
        if args.apply and newer:
            if apply_update(token):
                install_deps()
            print(f"Đã cập nhật lên v{new}.")
    except UpdateError as e:
        print(f"Lỗi: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
