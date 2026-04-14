param(
  [ValidateSet("env-check", "live-paper-daemon", "live-auto-trade-daemon")]
  [string]$Mode = "live-auto-trade-daemon",
  [string]$OutputBase = "quant_runtime"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Python {
  param([string[]]$PyArgs)
  if (Get-Command python -ErrorAction SilentlyContinue) {
    & python @PyArgs
    return
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @PyArgs
    return
  }
  throw "Python not found. Install Python 3.11+ first."
}

function Read-EnvFile {
  param([string]$Path)
  $map = @{}
  if (-not (Test-Path $Path)) { return $map }
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^\s*#') { continue }
    if ($line -match '^\s*([^=\s]+)\s*=\s*(.*)\s*$') {
      $key = $Matches[1].Trim()
      $val = $Matches[2].Trim().Trim("'`"")
      if ($key) { $map[$key] = $val }
    }
  }
  return $map
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

if (-not (Test-Path ".env")) {
  if (Test-Path "env.example") {
    Copy-Item -LiteralPath "env.example" -Destination ".env"
    Write-Host "[BOOT] .env was missing, copied from env.example."
    Write-Host "[BOOT] Fill real API keys in .env and run again."
    exit 1
  }
  throw ".env is missing and env.example was not found."
}

if (-not (Test-Path ".venv")) {
  Invoke-Python -PyArgs @("-m", "venv", ".venv")
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "venv python not found: $venvPython"
}

& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r requirements-live.txt | Out-Null

$envMap = Read-EnvFile -Path ".env"
if ($Mode -eq "live-auto-trade-daemon") {
  foreach ($required in @("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE")) {
    if (-not $envMap.ContainsKey($required) -or [string]::IsNullOrWhiteSpace($envMap[$required])) {
      throw "Missing required $required in .env"
    }
    $value = $envMap[$required].Trim().ToLowerInvariant()
    if ($value.StartsWith("your_") -or $value.Contains("change_me") -or $value.Contains("placeholder")) {
      throw "$required still looks like a placeholder value."
    }
  }
}

if (-not $envMap.ContainsKey("BITGET_MARGIN_MODE")) {
  $env:BITGET_MARGIN_MODE = "isolated"
  Write-Host "[BOOT] BITGET_MARGIN_MODE not found in .env, using process default isolated."
}

$exchange = if ($envMap.ContainsKey("EXCHANGE") -and -not [string]::IsNullOrWhiteSpace($envMap["EXCHANGE"])) { $envMap["EXCHANGE"] } else { "bitget" }
$syncInterval = if ($env:SYNC_INTERVAL_SECONDS) { $env:SYNC_INTERVAL_SECONDS } else { "60" }
$equityUsd = if ($env:EQUITY_USD) { $env:EQUITY_USD } else { "53" }
$maxRetries = if ($env:MAX_RETRIES) { $env:MAX_RETRIES } else { "999999" }

& $venvPython -m quant_binance.runtime --mode env-check --exchange $exchange
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Mode -eq "env-check") { exit 0 }

$args = @(
  "-m", "quant_binance.runtime",
  "--mode", $Mode,
  "--exchange", $exchange,
  "--output-base", $OutputBase,
  "--max-retries", $maxRetries,
  "--sync-interval-seconds", $syncInterval,
  "--insecure-ssl"
)

if ($Mode -eq "live-auto-trade-daemon") {
  $args += @("--equity-usd", $equityUsd, "--ack-live-risk", "I_UNDERSTAND_LIVE_TRADING")
}

& $venvPython @args
exit $LASTEXITCODE
