<#
.SYNOPSIS
  創客入門：一鍵裝好 VS Code＋Codex 擴充功能＋ESP32 上傳工具（Windows）。

.DESCRIPTION
  一律用最新版（Ted 2026-11-04）：缺的裝最新版、已裝的更新到最新版，可以重跑：
    1. winget（Windows 內建的安裝工具）
    2. VS Code（裝在使用者帳號底下，不需要系統管理員；已裝就更新）
    3. Python（沒有或低於 3.10 才裝，裝 winget 上最新的 3.x）
    4. uv（裝 mpremote、esptool 用；已裝就更新）
    5. VS Code 擴充功能：Codex、Python、Serial Monitor（已裝就更新）
    6. ESP32 資料夾：uv sync --upgrade（最新 mpremote、esptool），再跑 tools\check_env.ps1 看結果
  不會裝 USB 驅動（要系統管理員），也不會碰任何金鑰。
  Windows PowerShell 5.1 與 PowerShell 7 都能跑。

.PARAMETER EspFolder
  ESP32 資料夾（看得到 .vscode 和 tools 的那一層）。不填就找本腳本所在的資料夾。

.PARAMETER NoOpen
  裝完不要自動打開 VS Code。

.EXAMPLE
  雙擊 setup-vscode-codex.cmd
  或：powershell -ExecutionPolicy Bypass -File .\setup-vscode-codex.ps1
#>
param(
    [string]$EspFolder = "",
    [switch]$NoOpen
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$results = New-Object System.Collections.ArrayList

function Add-Result($name, $ok, $msg) {
    [void]$results.Add([pscustomobject]@{ Name = $name; OK = $ok; Msg = $msg })
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $extra = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\bin"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
    )
    $env:Path = (@($machine, $user) + $extra) -join ";"
}

function Test-Winget {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Install-WithWinget($id, $label) {
    Write-Host "  -> 用 winget 安裝 $label（$id）..." -ForegroundColor Cyan
    & winget install -e --id $id --scope user --silent --disable-interactivity --accept-package-agreements --accept-source-agreements 2>&1 |
        Where-Object { $_ -match "\S" -and $_ -notmatch "^\s*[-\\|/]\s*$" -and $_ -notmatch "[█▒]" } |
        ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    Update-SessionPath
}

function Update-WithWinget($id, $label) {
    Write-Host "  -> 檢查 $label 有沒有新版 ..." -ForegroundColor Cyan
    & winget upgrade -e --id $id --silent --disable-interactivity --accept-package-agreements --accept-source-agreements 2>&1 |
        Where-Object { $_ -match "\S" -and $_ -notmatch "^\s*[-\\|/]\s*$" -and $_ -notmatch "[█▒]" } |
        ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    Update-SessionPath
}

function Get-LatestPythonId {
    # winget 上 Python.Python.3.N 取 N 最大的那個；查不到就用 3.14（2026-11-04 最新）
    $best = -1
    foreach ($line in (& winget search --id Python.Python.3 --source winget --accept-source-agreements --disable-interactivity 2>$null)) {
        if ($line -match "Python\.Python\.3\.(\d+)\b") {
            $n = [int]$Matches[1]
            if ($n -gt $best) { $best = $n }
        }
    }
    if ($best -lt 0) { $best = 14 }
    return "Python.Python.3.$best"
}

function Get-CodeCmd {
    $known = Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\bin\code.cmd"
    if (Test-Path $known) { return $known }
    foreach ($p in @("$env:ProgramFiles\Microsoft VS Code\bin\code.cmd", "${env:ProgramFiles(x86)}\Microsoft VS Code\bin\code.cmd")) {
        if (Test-Path $p) { return $p }
    }
    $cmd = Get-Command code.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-PythonVersion {
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        # WindowsApps 裡的 python.exe 只是開 Microsoft Store 的捷徑，不算有裝
        if ($cmd.Source -match "WindowsApps") { continue }
        $out = (& $name --version 2>&1 | Out-String)
        if ($out -match "Python (\d+)\.(\d+)") {
            return [pscustomobject]@{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Text = $out.Trim() }
        }
    }
    return $null
}

Write-Host ""
Write-Host "=== 創客入門：安裝 VS Code＋Codex＋ESP32 工具 ===" -ForegroundColor Cyan
Write-Host "裝過的會自動跳過，中途失敗可以直接重跑。" -ForegroundColor Gray
Write-Host ""
Update-SessionPath

# ---------- 1. winget ----------
Write-Host "[1/6] 檢查 winget ..." -ForegroundColor Yellow
$hasWinget = Test-Winget
if ($hasWinget) {
    Write-Host "  OK: winget $((& winget --version 2>&1 | Out-String).Trim())" -ForegroundColor Green
    Add-Result "winget" $true "可用"
} else {
    Write-Host "  !! 找不到 winget（Microsoft Store 的「應用程式安裝程式」）。VS Code 改用官方安裝檔，其他項目請舉手。" -ForegroundColor Red
    Add-Result "winget" $false "找不到"
}

# ---------- 2. VS Code ----------
Write-Host "[2/6] 檢查 VS Code ..." -ForegroundColor Yellow
$code = Get-CodeCmd
if (-not $code) {
    if ($hasWinget) {
        Install-WithWinget "Microsoft.VisualStudioCode" "VS Code"
    } else {
        $setup = Join-Path $env:TEMP "VSCodeUserSetup-x64.exe"
        Write-Host "  -> 從 code.visualstudio.com 下載安裝檔 ..." -ForegroundColor Cyan
        try {
            Invoke-WebRequest -Uri "https://update.code.visualstudio.com/latest/win32-x64-user/stable" -OutFile $setup -UseBasicParsing
            Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/MERGETASKS=!runcode,addtopath" -Wait
        } catch {
            Write-Host "  !! 下載或安裝失敗：$($_.Exception.Message)" -ForegroundColor Red
        }
        Update-SessionPath
    }
    $code = Get-CodeCmd
} elseif ($hasWinget) {
    $userInstall = Test-Path (Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\Code.exe")
    $running = @(Get-Process Code -ErrorAction SilentlyContinue).Count -gt 0
    if ($running) {
        Write-Host "  -- VS Code 開著，這次不更新（它會自己更新；要馬上更新就關掉 VS Code 再跑一次）" -ForegroundColor Gray
    } elseif ($userInstall) {
        Update-WithWinget "Microsoft.VisualStudioCode" "VS Code"
    } else {
        Write-Host "  -- VS Code 裝在系統資料夾（要系統管理員才能更新），交給 VS Code 自己更新" -ForegroundColor Gray
    }
}
if ($code) {
    $ver = (& $code --version 2>&1 | Select-Object -First 1)
    Write-Host "  OK: VS Code $ver" -ForegroundColor Green
    Add-Result "VS Code" $true "$ver"
} else {
    Write-Host "  !! VS Code 沒裝好，請舉手。手動下載：https://code.visualstudio.com/" -ForegroundColor Red
    Add-Result "VS Code" $false "沒裝好"
}

# ---------- 3. Python ----------
Write-Host "[3/6] 檢查 Python 3.10 以上 ..." -ForegroundColor Yellow
$py = Get-PythonVersion
$pyOk = $py -and ($py.Major -gt 3 -or ($py.Major -eq 3 -and $py.Minor -ge 10))
if (-not $pyOk -and $hasWinget) {
    $pyId = Get-LatestPythonId
    Install-WithWinget $pyId "Python（$pyId）"
    $py = Get-PythonVersion
    $pyOk = $py -and ($py.Major -gt 3 -or ($py.Major -eq 3 -and $py.Minor -ge 10))
}
if ($pyOk) {
    Write-Host "  OK: $($py.Text)" -ForegroundColor Green
    Add-Result "Python" $true $py.Text
} else {
    Write-Host "  !! Python 沒裝好。手動下載：https://www.python.org/downloads/" -ForegroundColor Red
    Add-Result "Python" $false "沒裝好"
}

# ---------- 4. uv ----------
Write-Host "[4/6] 檢查 uv ..." -ForegroundColor Yellow
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if ($hasWinget) { Install-WithWinget "astral-sh.uv" "uv" }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "  -> 改用 uv 官方安裝程式 ..." -ForegroundColor Cyan
        try {
            $script = Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing
            & ([ScriptBlock]::Create($script)) | Out-Null
        } catch {
            Write-Host "  !! uv 安裝失敗：$($_.Exception.Message)" -ForegroundColor Red
        }
        Update-SessionPath
    }
} else {
    # winget 裝的用 winget 更新；官方安裝程式裝的用 uv self update
    $uvPath = (Get-Command uv).Source
    if ($hasWinget -and $uvPath -match "WinGet") {
        Update-WithWinget "astral-sh.uv" "uv"
    } else {
        Write-Host "  -> uv self update ..." -ForegroundColor Cyan
        & uv self update 2>&1 | Where-Object { $_ -match "\S" } | ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvVer = (& uv --version 2>&1 | Out-String).Trim()
    Write-Host "  OK: $uvVer" -ForegroundColor Green
    Add-Result "uv" $true $uvVer
} else {
    Write-Host "  !! uv 沒裝好，請舉手。" -ForegroundColor Red
    Add-Result "uv" $false "沒裝好"
}

# ---------- 5. VS Code 擴充功能 ----------
Write-Host "[5/6] 檢查 VS Code 擴充功能 ..." -ForegroundColor Yellow
$extensions = [ordered]@{
    "openai.chatgpt"                 = "Codex（OpenAI）"
    "ms-python.python"               = "Python"
    "ms-vscode.vscode-serial-monitor" = "Serial Monitor"
}
if ($code) {
    foreach ($id in $extensions.Keys) {
        $label = $extensions[$id]
        # --force：沒裝就裝，裝了就更新到最新版
        Write-Host "  -> 安裝／更新 $label（$id）..." -ForegroundColor Cyan
        & $code --install-extension $id --force 2>&1 | Where-Object { $_ -match "\S" } |
            ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    }
    $installed = @{}
    foreach ($line in (& $code --list-extensions --show-versions 2>$null)) {
        $parts = $line.Trim().ToLower() -split "@"
        if ($parts.Count -eq 2) { $installed[$parts[0]] = $parts[1] }
    }
    foreach ($id in $extensions.Keys) {
        $label = $extensions[$id]
        if ($installed.ContainsKey($id)) {
            Write-Host "  OK: $label $($installed[$id])" -ForegroundColor Green
            Add-Result "擴充功能 $label" $true "$id $($installed[$id])"
        } else {
            Write-Host "  !! $label 沒裝好" -ForegroundColor Red
            Add-Result "擴充功能 $label" $false $id
        }
    }
} else {
    Write-Host "  !! 沒有 VS Code，跳過" -ForegroundColor Red
    Add-Result "擴充功能" $false "沒有 VS Code"
}

# ---------- 6. ESP32 資料夾 ----------
Write-Host "[6/6] 準備 ESP32 資料夾 ..." -ForegroundColor Yellow
if (-not $EspFolder) { $EspFolder = $PSScriptRoot }
$isEsp = (Test-Path (Join-Path $EspFolder ".vscode\tasks.json")) -and (Test-Path (Join-Path $EspFolder "tools\check_env.ps1"))
if (-not $isEsp) {
    Write-Host "  -- $EspFolder 不是 ESP32 資料夾（找不到 .vscode\tasks.json 和 tools\check_env.ps1），跳過。" -ForegroundColor Gray
    Write-Host "     把這兩個 setup 檔放進 ESP32 資料夾最上層再跑一次，或加 -EspFolder <路徑>。" -ForegroundColor Gray
    Add-Result "ESP32 資料夾" $false "跳過（沒找到）"
} elseif (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Add-Result "ESP32 資料夾" $false "沒有 uv，跳過"
} else {
    # Windows 預設路徑上限 260 字元；.venv 裡最深的檔案再加約 93 字元（2026-11-04 實量），留餘裕抓 150
    $fullEsp = (Resolve-Path $EspFolder).Path
    if ($fullEsp.Length -gt 150) {
        Write-Host "  !! 資料夾放得太深（路徑 $($fullEsp.Length) 字元），工具可能讀不到自己的檔案。" -ForegroundColor Yellow
        Write-Host "     請把整個資料夾搬到短一點的位置，例如 C:\maker\$(Split-Path $fullEsp -Leaf)，再跑一次。" -ForegroundColor Yellow
        Add-Result "資料夾位置" $false "路徑太長（$($fullEsp.Length) 字元）"
    }
    Push-Location $EspFolder
    Write-Host "  -> uv sync --upgrade（最新 mpremote、esptool，第一次約 1 分鐘）..." -ForegroundColor Cyan
    & uv sync --upgrade 2>&1 | Where-Object { $_ -match "\S" } | ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    $okTools = (Test-Path ".venv\Scripts\mpremote.exe") -and (Test-Path ".venv\Scripts\esptool.exe")
    if ($okTools) {
        # 版本從 dist-info 資料夾名稱讀（mpremote-1.29.0.dist-info），讀不到就寫「?」，不讓它中斷
        $toolVer = (@("mpremote", "esptool") | ForEach-Object {
            $name = $_
            $ver = "?"
            try {
                $di = Get-ChildItem ".venv\Lib\site-packages" -Directory -Filter "$name-*.dist-info" -ErrorAction Stop | Select-Object -First 1
                if ($di -and $di.Name -match "^$name-(.+)\.dist-info$") { $ver = $Matches[1] }
            } catch {}
            "$name $ver"
        }) -join "、"
        Write-Host "  OK: $toolVer" -ForegroundColor Green
        Add-Result "ESP32 上傳工具" $true $toolVer
    } else {
        Write-Host "  !! mpremote／esptool 沒裝好" -ForegroundColor Red
        Add-Result "ESP32 上傳工具" $false "uv sync 失敗"
    }
    Write-Host ""
    Write-Host "  -> 跑 ESP32 資料夾自己的環境檢查（tools\check_env.ps1）..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File "tools\check_env.ps1"
    Pop-Location
}

# ---------- 總結 ----------
Write-Host ""
Write-Host "=== 結果 ===" -ForegroundColor Cyan
foreach ($r in $results) {
    $mark = if ($r.OK) { "OK" } else { "!!" }
    $color = if ($r.OK) { "Green" } else { "Red" }
    Write-Host ("  {0}  {1}：{2}" -f $mark, $r.Name, $r.Msg) -ForegroundColor $color
}
Write-Host ""
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "  1. VS Code 問「是否信任這個資料夾的作者」→ 按 Yes, I trust the authors。"
Write-Host "     上方出現 Restricted Mode 黃條 → 按 Manage → Trust。沒信任的話 Codex 和 ESP32 任務都不能用。"
Write-Host "  2. 在 VS Code 左邊找 Codex 圖示（沒看到就 Ctrl+Shift+P → Codex: Open Codex Sidebar）。"
Write-Host "     右邊那個 Chat 面板是 GitHub Copilot，不是 Codex，跳出 GitHub 登入可以按 Cancel。"
Write-Host "  3. Codex 還沒登入的畫面按 Use API Key，貼上你在課程專案建的金鑰，按 OK。"
Write-Host "  4. 金鑰只貼在那一格；用完記得登出（教室電腦一定要）。"
Write-Host "  5. USB 驅動如果上面顯示有問題，舉手找助教（要系統管理員權限）。"
Write-Host ""

if ($code -and $isEsp -and -not $NoOpen) {
    Write-Host "打開 VS Code ..." -ForegroundColor Cyan
    & $code $EspFolder
}
