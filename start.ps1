$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Checking ComfyUI on 127.0.0.1:8188 ..."
try {
    Invoke-RestMethod "http://127.0.0.1:8188/system_stats" -TimeoutSec 3 | Out-Null
    Write-Host "ComfyUI is running."
} catch {
    Write-Host "ComfyUI is not reachable. Open Comfy Desktop first, then rerun this script." -ForegroundColor Yellow
}

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python virtualenv..."
    python -m venv (Join-Path $Root "backend\.venv")
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $Root "backend\requirements.txt")
}

$backend = Start-Process -FilePath $venvPython -ArgumentList @(
    "-m", "uvicorn", "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8787",
    "--app-dir", (Join-Path $Root "backend")
) -PassThru -WindowStyle Hidden

Write-Host "Backend PID $($backend.Id) -> http://127.0.0.1:8787"
Start-Sleep -Seconds 1

try {
    Set-Location (Join-Path $Root "frontend")
    Write-Host "Frontend -> http://127.0.0.1:5173"
    npm run dev
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
