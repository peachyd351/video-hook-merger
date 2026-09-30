# Video Hook Merger

Ghép 3 clip dọc thành 1 video Reels: cắt khoảng lặng, tăng tốc và đồng bộ tốc độ nói,
tự thiết kế chữ hook tiếng Việt nằm sau người mẫu, xuất kèm ảnh cover.

## Cài đặt (1 lần trên mỗi máy)

1. Tải code về (nút **Code → Download ZIP** trên GitHub) rồi giải nén ra chỗ cố định, ví dụ `D:\Video Hook Merger`.
2. Bấm đúp **`Setup.bat`**, trả lời **Y** một lần. Tool tự cài Python, ffmpeg và thư viện (~3 GB trên máy có card NVIDIA, ~800 MB trên máy không có), tự kiểm tra, rồi tạo shortcut **"Video Hook Merger"** trên Desktop.
   Mất mạng giữa chừng thì cứ bấm lại `Setup.bat`: tool cài tiếp phần còn thiếu.

## Dùng

Bấm đúp shortcut **Video Hook Merger** (hoặc `Video Hook Merger.bat`):

1. **Chọn clip:** "Thêm clip…" hoặc "Chọn thư mục…"; dùng ▲/▼ để đổi thứ tự.
2. **Câu hook:** gõ câu hook, hoặc để trống để tool tự lấy từ tên file `b1…`. Câu ngắn tự thành 1 dòng đậm; câu dài được chia 2 dòng (dòng nhỏ nghiêng + dòng đậm). Dấu `|` để tự chia dòng, `*…*` để chọn chữ tô màu nhấn.
3. **Tuỳ chọn:** tốc độ (mặc định 1.15), đồng bộ tốc độ nói, cắt khoảng lặng, phong cách chữ.
4. Bấm **▶ GHÉP VIDEO**. Video và ảnh cover được lưu ngay trong thư mục chứa clip.

## Cập nhật

Bấm nút **⟳ Cập nhật** ở góc trên app. Lần đầu, app hỏi **GitHub token** (repo này để private):
github.com → ảnh đại diện → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
Ở mục *Repository access* chỉ chọn repo này, ở *Permissions → Contents* chọn **Read-only**, rồi dán token vào app.
Token được lưu trong `%APPDATA%\VideoHookMerger` của máy đó, không nằm trong thư mục app.

Cập nhật chỉ chép code mới. Thư viện đã cài và model được giữ nguyên, nên không phải tải lại.

## Thư mục

| | |
|---|---|
| `Setup.bat` | Cài đặt / kiểm tra / sửa lỗi (`Setup.bat -DryRun` chỉ kiểm tra) |
| `Video Hook Merger.bat` | Mở app (kéo thả clip lên file này để điền sẵn) |
| `app\` | Code, font, model, thư viện (không cần mở). Tài liệu kỹ thuật và dòng lệnh: `app\README.md` |
