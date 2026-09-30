# Cài đặt + tự kiểm tra Video Hook Merger bằng 1 lần bấm (gọi từ Setup.bat ở thư mục ngoài).
# Chỉ hỏi người dùng 1 lần trước khi cài/tải bất cứ thứ gì.
#   Setup.bat            cài đặt đầy đủ
#   Setup.bat -DryRun    chỉ kiểm tra máy và in kế hoạch, không cài gì
param([switch]$DryRun, [switch]$Yes, [switch]$NoShortcut, [ValidateSet("auto", "cuda", "cpu")][string]$Torch = "auto")

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path   # thư mục app (chứa file này)
$Top = Split-Path -Parent $Root                           # thư mục ngoài cùng
$Log = Join-Path $Root "setup.log"
Start-Transcript -Path $Log -Force | Out-Null

# Nâng cấp từ bản cũ (mọi thứ nằm ở thư mục ngoài): chuyển thư viện + model vào app\ để khỏi tải lại,
# rồi dọn các file cũ của tool ở thư mục ngoài.
foreach ($d in ".venv", ".cache") {
    $old = Join-Path $Top $d; $new = Join-Path $Root $d
    if ((Test-Path $old) -and -not (Test-Path $new)) {
        if ($DryRun) { Write-Host "   (DryRun) Sẽ chuyển $d từ bản cũ vào app\" -ForegroundColor Yellow; continue }
        Move-Item $old $new
        Write-Host "   Đã chuyển $d từ bản cũ vào app\ (không phải tải lại)" -ForegroundColor Green
    }
}
# (không có setup.bat: tên cũ trùng Setup.bat mới vì Windows không phân biệt hoa thường)
$legacy = @("GhepVideo.bat", "KiemTra.bat", "CaiDat.bat", "gui.py", "hook_merge.py", "design.py",
            "speech_rate.py", "install.py", "verify.py", "setup.ps1", "install.sh", "verify.sh", "requirements.txt",
            "PACKAGE.json", "hooks.txt", "SKILL.md", "MANIFEST.sha256", "setup.log", ".gui_settings.json", ".hook_history.json")
if (-not $DryRun) {
    foreach ($f in $legacy) {
        $p = Join-Path $Top $f
        if (Test-Path $p -PathType Leaf) { Remove-Item $p -Force }
    }
    foreach ($d in "fonts", "models", "bin", "__pycache__") {
        $p = Join-Path $Top $d
        if ((Test-Path $p) -and (Test-Path (Join-Path $Root $d))) { Remove-Item $p -Recurse -Force }
    }
}

function Step($n, $text) { Write-Host ""; Write-Host "[$n/5] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "   OK   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   !!   $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ""; Write-Host "LỖI: $text" -ForegroundColor Red
    Write-Host "Nhật ký chi tiết: $Log"
    Stop-Transcript | Out-Null
    exit 1
}

function Refresh-Path {
    # Nạp lại PATH từ registry để thấy phần mềm vừa cài mà không cần mở lại cửa sổ.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    $env:Path = "$machine;$user;$links"
}

function Find-Python {
    # Trả về đường dẫn python.exe 3.9-3.13 thật (bỏ qua bản giả của Microsoft Store).
    $cands = New-Object System.Collections.ArrayList
    if (Get-Command py -ErrorAction SilentlyContinue) { [void]$cands.Add(@("py", "-3")) }
    foreach ($n in "python", "python3") {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notmatch "WindowsApps") { [void]$cands.Add(@($c.Source)) }
    }
    $known = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe")
    foreach ($k in $known) {
        Get-ChildItem $k -ErrorAction SilentlyContinue | Sort-Object FullName -Descending |
            ForEach-Object { [void]$cands.Add(@($_.FullName)) }
    }
    foreach ($cand in $cands) {
        $exe = $cand[0]
        $rest = @($cand | Select-Object -Skip 1)
        try {
            $out = & $exe @rest -c "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
            $lines = @($out)
            $ver = [version]$lines[1]
            if ($ver -ge [version]"3.9" -and $ver -le [version]"3.13") { return $lines[0] }
        } catch { }
    }
    return $null
}

function Test-Ffmpeg { [bool](Get-Command ffmpeg -ErrorAction SilentlyContinue) -and [bool](Get-Command ffprobe -ErrorAction SilentlyContinue) }

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  VIDEO HOOK MERGER - CÀI ĐẶT + TỰ KIỂM TRA" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# ---------- 1. Kiểm tra máy ----------
Step 1 "Kiểm tra máy"
$py = Find-Python
if ($py) { Ok "Python: $py" } else { Warn "Chưa có Python 3.9-3.13" }
$hasFfmpeg = Test-Ffmpeg
if ($hasFfmpeg) { Ok "ffmpeg: $((Get-Command ffmpeg).Source)" } else { Warn "Chưa có ffmpeg" }
$gpu = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$gpuNote = ""
if ($gpu) {
    # Card quá cũ (compute < 5.0) hoặc ít VRAM (< 2 GB): torch GPU không chạy được / hay tràn bộ nhớ -> dùng CPU
    try {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $q = (& nvidia-smi --query-gpu=name,compute_cap,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        $ErrorActionPreference = $prev
        if ($q) {
            $parts = $q -split ",\s*"
            $gpuNote = "$($parts[0]), $([math]::Round([double]$parts[2] / 1024, 1)) GB VRAM"
            if (([double]$parts[1] -lt 5.0) -or ([double]$parts[2] -lt 2048)) {
                $gpu = $false
                $gpuNote += " (quá cũ hoặc ít VRAM -> dùng CPU)"
            }
        }
    } catch { $ErrorActionPreference = "Stop" }
}
if ($Torch -eq "auto") { if ($gpu) { $Torch = "cuda" } else { $Torch = "cpu" } }
if ($gpuNote) { Ok "Card: $gpuNote" }
if ($Torch -eq "cuda") { Ok "Dùng torch bản GPU (NVIDIA, nhanh)" }
elseif ($gpu) { Ok "Có card NVIDIA nhưng chọn bản CPU (-Torch cpu)" }
else { Ok "Không có card NVIDIA -> dùng bản CPU (chậm hơn, kết quả như nhau)" }
# .venv chỉ tính là xong khi import được đủ thư viện (lần trước có thể bị ngắt giữa chừng).
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$hasVenv = $false
if (Test-Path $venvPy) {
    try {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & $venvPy -c "import PIL, numpy, fontTools, faster_whisper, customtkinter, torch" 2>$null | Out-Null
        $hasVenv = ($LASTEXITCODE -eq 0) -and (Test-Path (Join-Path $Root ".cache\whisper-small\model.bin"))
    } catch { $hasVenv = $false } finally { $ErrorActionPreference = $prev }
    if ($hasVenv) { Ok "Thư viện Python đã cài đủ" } else { Warn "Thư viện Python cài dở (lần trước bị ngắt?) -> sẽ cài tiếp phần còn thiếu" }
}
$hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

# ---------- 2. Kế hoạch + hỏi 1 lần ----------
Step 2 "Kế hoạch cài đặt"
$plan = @()
if (-not $py) { $plan += "Cài Python 3.12 (winget, cho riêng tài khoản này, ~30 MB)" }
if (-not $hasFfmpeg) { $plan += "Cài ffmpeg (winget, ~100 MB)" }
if (-not $hasVenv) {
    $size = if ($Torch -eq "cuda") { "~2.5 GB" } else { "~250 MB" }
    $plan += "Tải/cài tiếp thư viện Python vào thư mục tool (.venv): Pillow, numpy, fontTools, faster-whisper, torch bản $($Torch.ToUpper()) (tối đa $size)"
    $plan += "Tải model Whisper small (~480 MB) để đồng bộ tốc độ nói giữa 3 clip"
}
$plan += "Tự kiểm tra + ghép thử 3 clip giả"
$plan += "Tạo shortcut 'Video Hook Merger' trên Desktop (mở giao diện)"
$plan | ForEach-Object { Write-Host "   - $_" }

if ((-not $py -or -not $hasFfmpeg) -and -not $hasWinget) {
    Write-Host ""
    Warn "Máy không có winget nên không tự cài Python/ffmpeg được. Hãy cài tay rồi chạy lại Setup.bat:"
    if (-not $py) { Write-Host "     Python: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')" }
    if (-not $hasFfmpeg) { Write-Host "     ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (giải nén, thêm thư mục bin vào PATH)" }
    Fail "Thiếu Python hoặc ffmpeg."
}
if ($DryRun) {
    Write-Host ""; Write-Host "(Chế độ -DryRun: dừng ở đây, chưa cài gì.)"
    Stop-Transcript | Out-Null
    exit 0
}
if (-not $Yes) {
    Write-Host ""
    $ans = Read-Host "Tiếp tục cài đặt? (Y/N)"
    if ($ans -notmatch "^(y|yes|c|co|có)$") {
        Write-Host "Đã huỷ, chưa cài gì."
        Stop-Transcript | Out-Null
        exit 1
    }
}
$wingetArgs = @("--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements")

# ---------- 3. Python + ffmpeg ----------
Step 3 "Python + ffmpeg"
if (-not $py) {
    Write-Host "   Đang cài Python 3.12 ..."
    winget install --id Python.Python.3.12 --scope user @wingetArgs
    Refresh-Path
    $py = Find-Python
    if (-not $py) { Fail "Chưa cài được Python (mất mạng / đổi IP giữa chừng?). Kiểm tra mạng rồi BẤM LẠI Setup.bat." }
}
Ok "Python: $py"
if (-not $hasFfmpeg) {
    Write-Host "   Đang cài ffmpeg ..."
    winget install --id Gyan.FFmpeg @wingetArgs
    Refresh-Path
    if (-not (Test-Ffmpeg)) {
        $bin = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($bin) { $env:Path = "$($bin.DirectoryName);$env:Path" }
    }
    if (-not (Test-Ffmpeg)) { Fail "Chưa cài được ffmpeg (mất mạng / đổi IP giữa chừng?). Kiểm tra mạng rồi BẤM LẠI Setup.bat. Vẫn lỗi thì khởi động lại máy rồi thử lại." }
}
Ok "ffmpeg: $((Get-Command ffmpeg).Source)"

# ---------- 4. Thư viện Python (.venv) ----------
Step 4 "Thư viện Python (.venv trong thư mục tool)"
& $py (Join-Path $Root "install.py") --torch $Torch --yes --skip-verify
if ($LASTEXITCODE -eq 3) { Fail "Tải thư viện bị gián đoạn (mất mạng / đổi IP?). Kiểm tra mạng rồi BẤM LẠI Setup.bat: tool sẽ cài tiếp phần còn thiếu." }
if ($LASTEXITCODE -ne 0) { Fail "Cài thư viện Python chưa thành công (xem thông báo ở trên)." }

# ---------- 5. Tự kiểm tra + chạy thử ----------
Step 5 "Tự kiểm tra + ghép thử 3 clip giả"
& $venvPy (Join-Path $Root "verify.py") --smoke
if ($LASTEXITCODE -ne 0) { Fail "Kiểm tra chưa đạt (xem các dòng [LỖI] ở trên)." }

# Shortcut trên Desktop: bấm đúp để mở giao diện; kéo thả clip lên shortcut để điền sẵn.
if (-not $NoShortcut) { try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Video Hook Merger.lnk"))
    $lnk.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = "`"$(Join-Path $Root 'gui.py')`""
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,18"
    $lnk.Description = "Ghép 3 clip + chữ hook"
    $lnk.Save()
    Ok "Đã tạo shortcut 'Video Hook Merger' trên Desktop"
} catch { Warn "Không tạo được shortcut Desktop (vẫn dùng được Video Hook Merger.bat)" } }

Write-Host ""
Write-Host "HOÀN TẤT! Bấm đúp shortcut 'Video Hook Merger' trên Desktop (hoặc Video Hook Merger.bat) để mở giao diện." -ForegroundColor Green
Stop-Transcript | Out-Null
exit 0
