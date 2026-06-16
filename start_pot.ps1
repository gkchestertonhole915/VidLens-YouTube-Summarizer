# 启动 bgutil PO Token 服务器（yt-dlp 绕 YouTube PO Token 必需，监听 127.0.0.1:4416）
# 每次重启电脑后、跑 VidLens 前先执行一次：  powershell -File start_pot.ps1

# 依赖自检：Deno 用于解 YouTube nsig（n-challenge），缺它会"Requested format is not available"
if (-not (Get-Command deno -ErrorAction SilentlyContinue)) {
    Write-Host "⚠️ 未检测到 Deno（解 nsig 必需）。正在安装：npm install -g deno ..."
    npm install -g deno
}

$server = "$PSScriptRoot\bgutil-ytdlp-pot-provider\server"
if (-not (Test-Path "$server\build\main.js")) {
    Write-Host "首次使用，正在编译 POT 服务器 ..."
    Push-Location $server; npm install; npx tsc; Pop-Location
}
# 已在运行就跳过
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:4416/ping" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "POT 服务器已在运行 (uptime=$($r.server_uptime)s)"; exit 0
} catch {}
Write-Host "启动 POT 服务器于 http://127.0.0.1:4416 ..."
Start-Process node -ArgumentList "`"$server\build\main.js`"","--port","4416" -WindowStyle Hidden
Start-Sleep -Seconds 3
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:4416/ping" -TimeoutSec 3
    Write-Host "OK，POT 服务器就绪 (version=$($r.version))"
} catch { Write-Host "启动失败，请检查 node 是否在 PATH" }
