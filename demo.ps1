<#
.SYNOPSIS
  One command to a running MPLADS Sentinel demo on Windows.

.DESCRIPTION
  Checks the environment, builds whatever is missing (pipeline outputs, app
  database, frontend bundle), guarantees the demo scenarios, starts the API and
  the dashboard, and opens the browser. Ctrl+C stops everything it started.

  Names are pseudonymised by default (PRESENTATION_MODE=1), because a demo is a
  publication. Pass -RealNames only on a private screen.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File demo.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File demo.ps1 -Smoke     # start, verify, stop
#>
param(
    [switch]$RealNames,   # show real MP and vendor names (private screens only)
    [switch]$Rebuild,     # reload the database and rebuild the frontend
    [switch]$Dev,         # Vite dev server with hot reload instead of the production build
    [switch]$Smoke,       # start everything, check it answers, then stop
    [switch]$NoBrowser,
    [int]$ApiPort = 8000,
    [int]$WebPort = 4173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Started = @()
# A fresh signing secret per demo run unless one is set; sessions end when the demo stops.
if (-not $env:JWT_SECRET) { $env:JWT_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N") }
$env:PYTHONIOENCODING = "utf-8"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Fail($text) { Write-Host "    $text" -ForegroundColor Red; exit 1 }

function Invoke-Checked([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "$exe $($arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Wait-Url([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -lt 500) { return $true }
        } catch { Start-Sleep -Milliseconds 700 }
    }
    return $false
}

function Stop-Started {
    foreach ($process in $Started) {
        if ($process -and -not $process.HasExited) {
            # /T takes the child tree too: npm starts node, uvicorn may start workers.
            & taskkill /PID $process.Id /T /F *> $null
        }
    }
}

try {
    Step "Checking the environment"
    if (-not (Test-Path $Python)) { Fail "No .venv found. Create it first: uv venv --python 3.12; uv pip install -e .[dev]" }
    Invoke-Checked $Python @("-c", "import fastapi, sqlalchemy, pandas, sklearn, jwt, apscheduler, fpdf; print('python imports OK')")
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "npm not found. Install Node.js 20 or later." }
    Ok "Python and Node available"

    Step "Pipeline outputs"
    if (-not (Test-Path "data\processed\scored_works.parquet")) {
        Write-Host "    No scored works yet: running the pipeline (a few minutes on a GPU)."
        Invoke-Checked $Python @("-m", "ml.train")
    }
    Ok "data\processed\scored_works.parquet present"

    Step "Application database"
    if ($Rebuild -or -not (Test-Path "data\app\sentinel.db")) {
        Invoke-Checked $Python @("-m", "backend.app.loader")
    }
    if (Test-Path "data\processed\planted_scored.parquet") {
        Invoke-Checked $Python @("-m", "backend.app.learning_seed")
    } else {
        Write-Host "    No planted cases (python -m ml.planted); the Learning page will say it needs verdicts."
    }
    Invoke-Checked $Python @("-m", "backend.app.demo_seed", "--reset")
    Ok "Database loaded and demo scenarios guaranteed"

    Step "Frontend"
    if (-not (Test-Path "frontend\node_modules")) { Invoke-Checked "npm" @("--prefix", "frontend", "ci") }
    if (-not $Dev -and ($Rebuild -or -not (Test-Path "frontend\dist\index.html"))) {
        Invoke-Checked "npm" @("--prefix", "frontend", "run", "build")
    }
    Ok "Frontend ready"

    Step "Starting the API on port $ApiPort"
    $env:PRESENTATION_MODE = $(if ($RealNames) { "0" } else { "1" })
    $env:SCHEDULER_ENABLED = "0"
    $env:SENTINEL_API = "http://127.0.0.1:$ApiPort"
    $env:SENTINEL_PREVIEW_PORT = "$WebPort"
    $api = Start-Process -FilePath $Python -PassThru -NoNewWindow `
        -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--log-level", "warning")
    $Started += $api
    if (-not (Wait-Url "http://127.0.0.1:$ApiPort/api/health" 90)) { Fail "The API did not answer on port $ApiPort." }
    Ok "API healthy (presentation mode: $env:PRESENTATION_MODE)"

    Step "Starting the dashboard"
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npm) { $npm = (Get-Command npm).Source }
    if ($Dev) {
        $WebPort = 5173
        $web = Start-Process -FilePath $npm -PassThru -NoNewWindow -ArgumentList @("--prefix", "frontend", "run", "dev")
    } else {
        $web = Start-Process -FilePath $npm -PassThru -NoNewWindow -ArgumentList @("--prefix", "frontend", "run", "preview")
    }
    $Started += $web
    $url = "http://127.0.0.1:$WebPort"
    if (-not (Wait-Url "$url/login" 90)) { Fail "The dashboard did not answer on port $WebPort." }
    if (-not (Wait-Url "$url/api/health" 30)) { Fail "The dashboard is up but its /api proxy cannot reach the API." }
    Ok "Dashboard at $url"

    if ($Smoke) {
        $login = Invoke-RestMethod -Method Post -Uri "$url/api/auth/login" -ContentType "application/json" `
            -Body '{"email":"ministry@demo","password":"demo123"}'
        $overview = Invoke-RestMethod -Uri "$url/api/overview" -Headers @{ Authorization = "Bearer $($login.access_token)" }
        Ok "Smoke check: signed in as ministry@demo, $($overview.kpis.works) works in scope"
        return
    }

    Write-Host ""
    Write-Host "  MPLADS Sentinel is running at $url" -ForegroundColor Yellow
    Write-Host "  Demo accounts (password demo123): ministry@demo, state.up@demo, district.lucknow@demo, mp.0147@demo"
    Write-Host "  Citizen view: $url/public"
    Write-Host "  Press Ctrl+C to stop."
    if (-not $NoBrowser) { Start-Process "$url/login" }
    while ($true) {
        Start-Sleep -Seconds 2
        if ($api.HasExited) { Fail "The API stopped unexpectedly." }
    }
} finally {
    Stop-Started
}
