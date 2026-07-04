param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8899,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5899,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$VenvCli = Join-Path $Root ".venv\Scripts\vibe-trading.exe"
$BackendBaseUrl = "http://$BackendHost`:$BackendPort"
$BackendHealthUrl = "$BackendBaseUrl/health"
$FrontendUrl = "http://$FrontendHost`:$FrontendPort"

function Test-UrlReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-UrlReady {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    Write-Host "Waiting for $Name at $Url ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-UrlReady -Url $Url) {
            Write-Host "$Name is ready."
            return $true
        }
        Start-Sleep -Seconds 1
    }

    Write-Warning "$Name did not become ready within $TimeoutSeconds seconds. Check the opened terminal window."
    return $false
}

if (-not (Test-Path -LiteralPath $FrontendDir)) {
    throw "Frontend directory not found: $FrontendDir"
}

if (-not (Get-Command "npm" -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js first, then run this script again."
}

if (Test-Path -LiteralPath $VenvCli) {
    $VibeTradingCommand = $VenvCli
}
elseif (Get-Command "vibe-trading" -ErrorAction SilentlyContinue) {
    $VibeTradingCommand = "vibe-trading"
}
else {
    throw "vibe-trading was not found. Expected $VenvCli or a vibe-trading command on PATH."
}

Write-Host "Vibe-Trading Web UI startup"
Write-Host "Backend:  $BackendBaseUrl"
Write-Host "Frontend: $FrontendUrl"

if (Test-UrlReady -Url $BackendHealthUrl) {
    Write-Host "Backend is already running."
}
else {
    $backendScript = "& `"$VibeTradingCommand`" serve --host $BackendHost --port $BackendPort"
    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $Root `
        -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $backendScript)
    if (-not (Wait-UrlReady -Name "Backend" -Url $BackendHealthUrl)) {
        throw "Backend did not become ready. Keep the backend terminal window open and check its error output before starting the frontend."
    }
}

if (Test-UrlReady -Url $FrontendUrl) {
    Write-Host "Frontend is already running."
}
else {
    $frontendScript = @"
Set-Location -LiteralPath "$FrontendDir"
if (-not (Test-Path -LiteralPath "node_modules")) {
    npm install
}
`$env:VITE_API_URL = "$BackendBaseUrl"
npm run dev -- --host $FrontendHost --port $FrontendPort
"@

    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $FrontendDir `
        -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendScript)
    if (-not (Wait-UrlReady -Name "Frontend" -Url $FrontendUrl)) {
        throw "Frontend did not become ready. Check the frontend terminal window for Vite or npm errors."
    }
}

Write-Host ""
Write-Host "Web UI:   $FrontendUrl"
Write-Host "API docs: $BackendBaseUrl/docs"

if (-not $NoOpen) {
    Start-Process $FrontendUrl
}
