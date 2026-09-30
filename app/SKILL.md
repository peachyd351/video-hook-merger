---
name: video-hook-merger
description: Ghép 3 clip dọc (thời trang, người mẫu nói) thành 1 video Reels, cắt khoảng lặng và jump cut, tăng tốc hình + giọng, tự thiết kế hook text 2 dòng tiếng Việt nằm sau người mẫu. Dùng khi người dùng đưa 3 clip (hoặc 1 thư mục clip) và một câu hook, hoặc bảo "ghép video + chèn text" theo kiểu "Nàng mặc đẹp".
---

# Video Hook Merger

Người dùng thường dùng giao diện (`Video Hook Merger.bat` / shortcut Desktop → `app/gui.py`). Agent dùng CLI `bin/hook-merge` như bên dưới.

Code nằm trong thư mục `app\` (chứa file này); thư mục ngoài chỉ có `Setup.bat`, `Video Hook Merger.bat`, `README.md`. Đọc `README.md` để biết chi tiết tuỳ chọn.

## Quy trình cho agent

1. **Kiểm tra trước:** chạy `./verify.sh` (Windows: `Setup.bat -DryRun` hoặc `.venv\Scripts\python.exe verify.py`).
   Nếu chưa cài: trên Windows đề nghị người dùng bấm `Setup.bat` (tự cài Python/ffmpeg/thư viện sau khi hỏi họ 1 lần). Hoặc chạy `./install.sh`. Installer sẽ hỏi trước khi tải (~250 MB bản CPU, ~2.5 GB bản GPU); **hỏi người dùng** trước khi trả lời "y".
   Nếu thiếu ffmpeg: **không tự cài phần mềm hệ thống**, hãy đưa lệnh cho người dùng tự chạy (`winget install Gyan.FFmpeg` / `brew install ffmpeg`).
2. **Xác định input:** 3 clip theo thứ tự người dùng đưa (truyền từng file theo đúng thứ tự), hoặc 1 thư mục (ghép theo thứ tự tên file).
   Hook lấy theo thứ tự ưu tiên: `--hook "câu"` → `hook.txt` trong thư mục → tên file `b1<câu hook>` trong thư mục → kho `hooks.txt`.
3. **Chạy:**
   ```
   bin/hook-merge clip1.mp4 clip2.mp4 clip3.mp4 -o out.mp4 --hook "Một chút điệu đà cho buổi tiệc tối nay" --speed 1.15
   ```
   Tốc độ mặc định là 1.15; người dùng muốn nhanh/chậm hơn thì đổi `--speed` (0.5–2.0).
   Tool tự đồng bộ tốc độ nói giữa các clip (Whisper, ±12% quanh `--speed`); `--no-sync-speed` để tắt.
4. **Kiểm tra kết quả:** đọc log in ra (thời lượng cắt từng clip, phong cách chữ, % chữ bị tóc che ở frame đầu).
5. **Báo cáo** cho người dùng: đường dẫn `out.mp4`, thời lượng, phong cách chữ đã chọn và lý do, những chỗ cần họ tự nghe lại (jump cut).

## Quy tắc

- Không đổi form chữ mặc định (dòng 1 nghiêng mảnh nhỏ, dòng 2 serif Bold) trừ khi người dùng yêu cầu; dùng `--style` để ép phong cách.
- Chữ mặc định nằm SAU người mẫu (tóc được đè lên chữ). Chỉ dùng `--text-layer auto/front` khi người dùng muốn thumbnail đọc trọn chữ.
- Vạch an toàn trên cùng mặc định 8% (tai thỏ / Dynamic Island). Chỉ giảm `--safe-top` khi người dùng yêu cầu.
- Không đăng/upload video đi đâu nếu người dùng không yêu cầu.
