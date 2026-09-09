param([switch]$Recover)

$ErrorActionPreference = 'Stop'
$dockerRun = Join-Path $env:LOCALAPPDATA 'Docker\run'
$knownStaleSockets = @(
    (Join-Path $dockerRun 'dockerInference'),
    (Join-Path $dockerRun 'userAnalyticsOtlpHttp.sock')
)

docker info *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Docker engine is healthy.'
    exit 0
}

$detectedSockets = @($knownStaleSockets | Where-Object { Test-Path -LiteralPath $_ })
if ($detectedSockets.Count -eq 0) {
    Write-Error 'Docker engine is unavailable, but no known stale Docker Desktop socket was found.'
}

if (-not $Recover) {
    $names = ($detectedSockets | ForEach-Object { Split-Path -Leaf $_ }) -join ', '
    Write-Error "Known stale Docker Desktop socket detected ($names). Re-run with -Recover for the reversible recovery."
}

Get-Process 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue |
    Stop-Process -Force
wsl.exe --terminate docker-desktop *> $null
$suffix = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$dockerRun.stale-$suffix"
Move-Item -LiteralPath $dockerRun -Destination $backup
Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
Write-Host "Moved the transient Docker run directory to $backup and restarted Docker Desktop."
Write-Host 'No images, volumes, containers, or project data were removed.'
