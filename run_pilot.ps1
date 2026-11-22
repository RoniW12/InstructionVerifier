# Runs the TeachBack pilot on this PC: sample records, generate texts, verify, build rows.
# Everything it prints goes to Data\pilot\run-<date>-<time>.log
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Code = Join-Path $Root "Code"
$LogDir = Join-Path $Root "Data\pilot"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("run-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".log")
Start-Transcript -Path $Log | Out-Null
try {
    # 1. Keys come from .env (KEY=VALUE per line), because a scheduled task does not see $env: values set in a window.
    $EnvFile = Join-Path $Root ".env"
    if (Test-Path $EnvFile) {
        Get-Content $EnvFile | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$' } | ForEach-Object {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), "Process") }
    }
    if (-not $env:OPENAI_API_KEY) { throw "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in." }

    # 2. Python environment (created on first run)
    $Py = Join-Path $Code ".venv\Scripts\python.exe"
    if (-not (Test-Path $Py)) {
        Write-Host "Creating the Python environment..."
        python -m venv (Join-Path $Code ".venv")
        & $Py -m pip install -q -r (Join-Path $Code "requirements.txt")
    }
    Set-Location $Code

    # 3. Does the generator model exist on this OpenAI account?
    $Model = (Select-String -Path "configs\gen.yaml" -Pattern '^\s+model:\s*(\S+)' | Select-Object -First 1).Matches.Groups[1].Value
    try {
        Invoke-RestMethod -Uri "https://api.openai.com/v1/models/$Model" -Headers @{ Authorization = "Bearer $env:OPENAI_API_KEY" } | Out-Null
        Write-Host "Generator model OK: $Model"
    } catch { throw "OpenAI does not accept the model '$Model' with this key. Set models.generator.model in Code\configs\gen.yaml." }

    # 4. Is the verifier running? If not, generate now and verify later.
    $VerifyFlag = @()
    $VerUrl = (Select-String -Path "configs\gen.yaml" -Pattern 'base_url:\s*(http\S+)' | Select-Object -First 1).Matches.Groups[1].Value
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri ($VerUrl.TrimEnd('/') + "/models") | Out-Null
        Write-Host "Verifier reachable at $VerUrl"
    } catch {
        Write-Host "Verifier NOT reachable at $VerUrl. Generating without verification."
        Write-Host "Later, with the verifier running: python -m data_gen.generate --pilot --verify-only; python -m data_gen.build_rows --pilot"
        $VerifyFlag = @("--no-verify")
    }

    # 5. The pilot
    & $Py -m pytest -q;                              if ($LASTEXITCODE) { throw "tests failed" }
    & $Py -m data_gen.sample_records --pilot;        if ($LASTEXITCODE) { throw "sample_records failed" }
    & $Py -m data_gen.generate --pilot @VerifyFlag;  if ($LASTEXITCODE) { throw "generate failed" }
    if ($VerifyFlag.Count -eq 0) {
        & $Py -m data_gen.build_rows --pilot;        if ($LASTEXITCODE) { throw "build_rows failed" }
    }
    Write-Host "PILOT FINISHED. Outputs in Data\pilot, EDA in Results. Log: $Log"
} catch {
    Write-Host "PILOT STOPPED: $_"
} finally {
    Stop-Transcript | Out-Null
}
