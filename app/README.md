# Video Hook Merger (tài liệu kỹ thuật)

Hướng dẫn ngắn cho người dùng nằm ở `../README.md`. Các lệnh dưới đây chạy trong thư mục `app\`.

Đầu vào: **3 clip** (theo thứ tự) và **1 câu hook**. Đầu ra: 1 video dọc đã cắt phần thừa và tăng tốc,
có hook text 2 dòng tiếng Việt nằm **sau** người mẫu, kèm ảnh cover.

## Cài trên máy mới (Windows): bấm 1 lần

Giải nén ZIP ra một thư mục bất kỳ, rồi **bấm đúp `Setup.bat`**. Tool tự làm hết 5 bước:

1. **Kiểm tra máy:** Python, ffmpeg, card NVIDIA, môi trường đã cài.
2. **In kế hoạch** (sẽ cài gì, tải bao nhiêu) và **hỏi 1 lần duy nhất** "Tiếp tục? (Y/N)".
3. **Cài Python 3.12 và ffmpeg bằng winget** nếu máy chưa có. Python chỉ cài cho tài khoản hiện tại.
4. **Tải thư viện** vào thư mục `.venv` của tool: máy có card NVIDIA lấy torch bản GPU (~2.5 GB), máy không có lấy bản CPU (~250 MB). Kèm model Whisper small (~480 MB) để đo tốc độ nói.
5. **Tự kiểm tra và ghép thử 3 clip giả.** Thấy dòng "HOÀN TẤT!" là dùng được.

- Model tách nền và font chữ đã đóng kèm, không cần tải thêm.
- Có lỗi thì tool dừng lại, ghi rõ bước bị lỗi, và lưu nhật ký chi tiết vào `setup.log`.
- Máy không có winget (Windows quá cũ) thì tool in link để bạn tự cài Python/ffmpeg, rồi chạy lại `Setup.bat`.
- Tuỳ chọn: `Setup.bat -DryRun` (chỉ kiểm tra máy, không cài gì), `Setup.bat -Torch cpu` (ép bản CPU nhẹ hơn).
- Muốn kiểm tra lại bất cứ lúc nào: chạy `Setup.bat -DryRun`. Dời thư mục tool sang chỗ khác: xoá thư mục `.venv` rồi chạy lại `Setup.bat`.

### Đang cài mà mất mạng / đổi IP?

**Cứ bấm lại `Setup.bat`.** Mỗi lần chạy, tool kiểm tra lại từng thứ và chỉ cài **tiếp phần còn thiếu**:

- Python hoặc ffmpeg cài chưa xong thì được cài lại.
- `.venv` bị tạo dở thì được giữ lại hoặc tạo lại, và chỉ tải những thư viện còn thiếu. File đã tải xong được pip giữ trong bộ nhớ đệm nên không phải tải lại.
- Mạng chập chờn: mỗi file được thử lại tối đa 10 lần. Nếu vẫn lỗi, tool dừng và báo "Tải bị gián đoạn… BẤM LẠI Setup.bat".
- Model Whisper tải dở cũng được tải tiếp khi bấm lại.
- Máy có card NVIDIA mà tải bản GPU lỗi do mạng thì tool **không** tự đổi sang bản CPU. Nếu lỗi lặp lại dù mạng ổn định, chạy `Setup.bat -Torch cpu`.
- Muốn xoá sạch để cài lại từ đầu: xoá thư mục `.venv` trong thư mục tool, rồi bấm `Setup.bat`.

macOS / Linux / Git Bash: `./install.sh`, `./verify.sh --smoke`, `bin/hook-merge ...` (tự cài ffmpeg trước).

## Cách dùng hằng ngày (giao diện)

Bấm đúp shortcut **"Video Hook Merger"** trên Desktop (hoặc `Video Hook Merger.bat`). Cửa sổ có 4 bước:

1. **Chọn clip:** bấm "Thêm clip…" (giữ Ctrl để chọn nhiều) hoặc "Chọn thư mục…". Dùng ▲/▼ để đổi thứ tự.
   Kéo thả clip hoặc thư mục lên shortcut / `Video Hook Merger.bat` thì clip được điền sẵn.
2. **Câu hook:** gõ câu hook. Để trống thì tool tự lấy từ `hook.txt` → tên file `b1…` → kho câu mẫu. Dùng `|` để tự chia 2 dòng.
3. **Tuỳ chọn:** tốc độ (mặc định 1.15), đồng bộ tốc độ nói, cắt khoảng lặng, phong cách chữ, thời gian hiện chữ. Tool nhớ lựa chọn cho lần sau.
4. **Lưu vào:** tự điền `<tên thư mục>_hook.mp4` cạnh thư mục clip; bấm "Chọn…" để đổi.

Bấm **▶ GHÉP VIDEO**, theo dõi thanh tiến trình. Xong thì ảnh cover hiện bên phải, bấm **Mở video** / **Mở thư mục** để xem. Bấm **Huỷ** để dừng giữa chừng.

### Nâng cấp lên bản mới (không phải tải lại thư viện)

Giải nén bản mới, **chép toàn bộ file trong đó đè lên thư mục tool cũ**, rồi bấm `Setup.bat`. Setup thấy thư viện và model đã đủ nên chỉ kiểm tra lại, không tải gì thêm.

## Tool làm gì

- **Cắt phần thừa:** dò khoảng lặng theo độ to từng 20ms, với ngưỡng tính riêng cho từng clip (thấp hơn giọng nói 20 dB, cao hơn tiếng nền 6 dB), nên clip có nhạc nền vẫn tìm được chỗ ngừng.
  - Đầu clip: bỏ đoạn đứng chờ, giữ 0.12s trước câu đầu.
  - Cuối clip: bỏ đoạn thừa, giữ 0.3s sau câu cuối.
  - Giữa câu (jump cut): khoảng ngừng dài hơn 0.45s được rút còn 0.2s.
- **Tốc độ:** hình và tiếng cắt cùng mốc, tăng tốc cùng hệ số, nên khẩu hình khớp. Giọng giữ nguyên cao độ, không bị the thé. Mỗi đoạn được ép đúng số nguyên frame, nên hình và tiếng không lệch nhau.
- **Đồng bộ tốc độ nói giữa 3 clip:** Whisper small đếm số chữ trong từng clip. Tiếng Việt mỗi chữ là một âm tiết, nên số chữ chia cho thời gian nói ra đúng tốc độ nói, và nhạc nền không làm sai kết quả. Tool lấy mức giữa của 3 clip làm chuẩn: clip nói chậm được tăng tốc thêm, clip nói nhanh được giảm bớt, quanh mức `--speed` và lệch tối đa ±12%. Chênh dưới 3% thì giữ nguyên. Log in ra số chữ/giây và tốc độ từng clip. Whisper chạy trong tiến trình riêng, GPU trước rồi CPU; máy chỉ có CPU mất thêm khoảng 40 giây mỗi video. Tắt bằng `--no-sync-speed`.
- **Chữ:** dòng 1 nhỏ, nghiêng, nét mảnh; dòng 2 serif Bold (form video mẫu "Nàng mặc đẹp"). Chữ hiện suốt cảnh đầu, căn giữa khoảng trống từ vạch an toàn (8%, tránh tai thỏ/Dynamic Island) tới đỉnh đầu người mẫu, và nằm **sau** người mẫu nên tóc đè lên chữ.
- **Tự thiết kế font + màu** (offline): chấm điểm 6 phong cách theo từ khoá trong câu hook và màu trang phục ở cả 3 clip; màu chữ lấy theo tông nền và đạt tương phản ≥ 4.5:1. Không dùng hiệu ứng: chỉ font, màu, vị trí.
- **An toàn tiếng Việt:** cả 10 font đều đủ 146 ký tự có dấu. Text được chuẩn hoá NFC; emoji và ký tự vô hình bị bỏ; font thiếu ký tự thì tự đổi sang font dự phòng.

| Phong cách | Dòng 1 | Dòng 2 | Màu dòng 2 lấy từ trang phục |
|---|---|---|---|
| `sang_trong` | Be Vietnam Pro Light Italic | Playfair Display Bold | không |
| `tap_chi` | Be Vietnam Pro Light | Fraunces SemiBold Italic | có |
| `lang_man` | TH Viettay (viết tay) | Fraunces SemiBold | có |
| `de_thuong` | TH Viettay (viết tay) | Yeseva One | có |
| `hien_dai` | Be Vietnam Pro Light | Be Vietnam Pro ExtraBold | không |
| `ca_tinh` | Be Vietnam Pro Medium Italic | UTM Bebas (IN HOA) | có |

## Dòng lệnh

```
bin\hook-merge.bat "D:\clips\28.9.1" --hook "Một chút điệu đà cho buổi tiệc tối nay" --speed 1.2
bin\hook-merge.bat 1.mp4 2.mp4 3.mp4 -o out.mp4 --hook "Hẹn hò cuối tuần | Diện ngay set này"
```

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--hook "câu"` | Câu hook (`\|` để tự chia 2 dòng). Bỏ trống: `hook.txt` → tên file `b1...` → `hooks.txt` |
| `--speed 1.15` | Tốc độ hình + giọng, từ 0.5 đến 2.0 (`1.1` = tốc độ video mẫu, `1` = giữ nguyên); là mức chung, từng clip lệch tối đa ±12% để nhịp nói đều |
| `--no-sync-speed` | Không đồng bộ tốc độ nói: cả 3 clip dùng đúng `--speed` |
| `--ask` | Hỏi hook và tốc độ trong cửa sổ (Video Hook Merger.bat dùng tuỳ chọn này) |
| `--style` | Ép phong cách: `sang_trong`, `tap_chi`, `lang_man`, `de_thuong`, `hien_dai`, `ca_tinh` |
| `--hook-dur clip1` | Thời gian hiện chữ: `clip1` = hết cảnh đầu (mặc định), hoặc số giây, vd `4` |
| `--safe-top 0.08` | Vùng cấm phía trên (tỉ lệ chiều cao) cho tai thỏ / hàng icon Reels |
| `--text-layer behind` | `behind` (mặc định): chữ sau người mẫu; `auto`: ưu tiên thumbnail đọc trọn chữ; `front`: chữ trước người mẫu |
| `--no-trim` | Không cắt khoảng lặng / jump cut |
| `--size 1080x1920`, `--fps 30` | Kích thước và fps đầu ra (mặc định theo clip đầu) |
| `--mute`, `--crf 18`, `--keep-png` | Bỏ tiếng gốc / chất lượng nén / lưu thêm PNG lớp chữ và `.design.txt` |

Ngưỡng cắt (`SPEECH_DROP`, `MAX_PAUSE`, `GAP_AFTER`...) nằm ở đầu `hook_merge.py`. Nếu jump cut làm hụt âm cuối của từ, tăng `GAP_AFTER`.

## Agent onboarding

Tool này chạy được với **agent có quyền chạy lệnh trên máy** (Claude Code, Codex CLI, Cursor agent...).
**Không** chạy được trên chatbot web (ChatGPT web, Claude.ai chat) vì các nền tảng đó không truy cập được file video và ffmpeg trên máy bạn.

Prompt mẫu để bắt đầu (dán vào agent, mở tại thư mục tool):

```
Đọc SKILL.md và README.md trong thư mục này. Chạy verify (Windows: .venv\Scripts\python.exe verify.py,
hoặc python verify.py nếu chưa có .venv). Nếu còn thiếu thư viện thì hỏi tôi trước khi chạy installer.
Sau đó ghép 3 clip sau theo đúng thứ tự, hook "<câu hook>", tốc độ 1.15:
<clip1> <clip2> <clip3>
Báo lại đường dẫn video + ảnh cover, phong cách chữ đã chọn, và những chỗ jump cut tôi cần nghe lại.
```

Thứ tự việc agent phải làm:

1. Chạy `verify.py` (hoặc `./verify.sh`) trước tiên.
2. Nếu chưa cài: trên Windows, đề nghị người dùng tự bấm `Setup.bat` (setup sẽ hỏi họ trước khi cài). Agent chỉ được chạy `install.py` / `./install.sh` sau khi **người dùng đồng ý**, vì bước này tải 250 MB–2.5 GB từ Internet.
3. Chạy `bin/hook-merge` (Windows: `bin\hook-merge.bat`) với 3 clip theo đúng thứ tự người dùng đưa.
4. Đọc log và xem ảnh cover, rồi báo cáo.

Giới hạn quyền của agent:

- **Không tự cài phần mềm hệ thống** (ffmpeg, Python, driver GPU). Chỉ đưa lệnh để người dùng tự chạy.
- Chỉ tải thư viện Python vào `.venv` của tool khi người dùng đã đồng ý.
- Tool không cần API key, không gọi dịch vụ trả phí, không upload video đi đâu. Không đăng video lên mạng xã hội nếu người dùng không yêu cầu.
- Không ghi đè video cũ ngoài đường dẫn `-o` hoặc đường dẫn mặc định `<thư mục>_hook.mp4`.

Kết quả bàn giao: `<tên>.mp4` + `<tên>.cover.jpg`. Báo đường dẫn, thời lượng, số giây đã cắt ở từng clip, phong cách chữ, và % chữ bị tóc che ở frame đầu.

## Giấy phép thành phần đóng kèm

- Model `models/rvm_mobilenetv3_fp32.torchscript`: Robust Video Matting v1.0.0 (PeterL1n), giấy phép GPL-3.0.
- Model Whisper small (Systran/faster-whisper-small, MIT), được `Setup.bat` tải về `.cache/whisper-small`, không có sẵn trong ZIP.
- Font Be Vietnam Pro, Playfair Display, Fraunces, Yeseva One: SIL Open Font License.
- Font UTM Bebas, TH Viettay: font Việt hoá của bên thứ ba. Kiểm tra giấy phép trước khi dùng thương mại hoặc phân phối lại.
