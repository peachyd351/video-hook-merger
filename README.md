# Video Hook Merger

Ghép 3 clip dọc thành 1 video Reels: cắt khoảng lặng, tăng tốc và đồng bộ tốc độ nói,
tự thiết kế chữ hook tiếng Việt nằm sau người mẫu.

## Cài đặt (1 lần trên mỗi máy)

1. Tải code về (nút **Code → Download ZIP** trên GitHub) rồi giải nén ra chỗ cố định, ví dụ `D:\Video Hook Merger`.
2. Bấm đúp **`Setup.bat`**, trả lời **Y** một lần. Tool tự cài Python, ffmpeg và thư viện (~3 GB trên máy có card NVIDIA, ~800 MB trên máy không có), tự kiểm tra, rồi tạo shortcut **"Video Hook Merger"** trên Desktop.
   Mất mạng giữa chừng thì cứ bấm lại `Setup.bat`: tool cài tiếp phần còn thiếu.

## Dùng

Bấm đúp shortcut **Video Hook Merger** (hoặc `Video Hook Merger.bat`):

1. **Chọn clip:** "Thêm clip…" hoặc "Chọn thư mục…"; dùng ▲/▼ để đổi thứ tự.
2. **Câu hook:** gõ **đủ cả câu hook**. Tool **chỉ xuống dòng ở dấu `|`**, không tự ngắt: không có `|` thì cả câu là 1 dòng đậm (dài quá thì chữ tự nhỏ lại cho vừa); có `|` thì dòng đầu nhỏ, các dòng sau đậm. Ví dụ `Không biết phối đồ đi tiệc|Cứ mặc nguyên *set này*`. `*…*` để chọn chữ tô màu nhấn. **Để trống thì video không có chữ** (chỉ ghép + cắt + tăng tốc, nhanh hơn).
   Khung **Xem trước** bên phải hiện ngay chữ hook trên cảnh đầu của clip 1 (người mẫu đè lên chữ đúng như video thật), tự vẽ lại khi gõ chữ, đổi kiểu chữ hay đổi clip — chọn được mẫu ưng ý rồi mới bấm Ghép.
3. **Tuỳ chọn:** tốc độ (mặc định 1.15), kiểu chữ (**Tự động** hoặc chọn 1 trong 17 mẫu: sang trọng, tạp chí, lãng mạn, dễ thương, hiện đại, vibe Hàn, cá tính, Montserrat, Lexend, Anton chữ hoa, Lora cổ điển, thư pháp, Dancing Script, Pacifico vui tươi, Josefin thanh mảnh, nhãn nền màu bo tròn…), đồng bộ tốc độ nói, cắt khoảng lặng, **cân bằng âm lượng giọng nói** (đo độ to từng clip rồi chỉnh cho bằng nhau, nén nhẹ cho đều tiếng giữa các câu, đưa cả video về -14 LUFS như chuẩn Reels/TikTok). Mục **Nâng cao ▸** có thời gian hiện chữ và nơi lưu video.
4. Bấm **Ghép video**. Xong thì bấm **Mở video** / **Mở thư mục**. Video được lưu ngay trong thư mục chứa clip. Có lỗi thì bấm **Chi tiết** để xem nhật ký.

## Máy yếu / không có card NVIDIA

Tool chạy được trên mọi máy Windows 10/11 64-bit (khuyến nghị RAM ≥ 8 GB). `Setup.bat` tự **chạy thử trên GPU và CPU** rồi chọn cấu hình hợp sức máy:

| Máy | Cách chạy | Thời gian cho 3 clip 10 giây (tham khảo) |
|---|---|---|
| Card NVIDIA ≥ 3.5 GB VRAM (GTX 1050 Ti 4 GB trở lên) | Tách nền 1080px + Whisper trên GPU | ~30 giây (GTX 1070 Ti), ~45–60 giây (GTX 1050 Ti, ước tính) |
| Card NVIDIA 2–3.5 GB VRAM | Tách nền 720px trên GPU, Whisper trên CPU | ~45–60 giây |
| Card quá cũ, < 2 GB VRAM, AMD/Intel, không có card | Toàn bộ trên CPU, tách nền 720px (máy yếu: 540px) | ~2–4 phút |

- Đã thử trên Xeon E5 v2 (chỉ có AVX, không AVX2): chạy tốt; Xeon E5 v3/v4 có AVX2 nên nhanh hơn. Toàn bộ quy trình dùng tối đa ~1.5 GB VRAM nên card 4 GB dư sức.
- GPU lỗi khi đang chạy (tràn bộ nhớ, driver lỗi…) thì tool **tự làm lại bước đó bằng CPU**, không dừng giữa chừng.
- Ép dùng CPU: đặt biến môi trường `VHM_FORCE_CPU=1`. Giới hạn số luồng CPU để máy vẫn mượt cho việc khác: `VHM_CPU_THREADS=4`.
- Đổi card hoặc driver thì bấm lại `Setup.bat` để kiểm tra lại.

## Cập nhật

App **tự kiểm tra bản mới mỗi khi mở** (và 3 tiếng một lần nếu để mở lâu). Có bản mới thì hiện dải thông báo **"Có bản mới vX.Y.Z"** ở đầu cửa sổ, bấm **Cập nhật** để cài (✕ để bỏ qua bản đó). Cũng có thể bấm nút **⟳ Cập nhật** ở góc trên bất cứ lúc nào. Lần đầu, app hỏi **GitHub token** (repo này để private):
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
