param([switch]$Recover)

$ErrorActionPreference = 'Stop'
$dockerRun = Join-Path $env:LOCALAPPDATA 'Docker\run'
$inferenceSocket = Join-Path $dockerRun 'dockerInference'

docker info *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Docker engine is healthy.'
    exit 0
}

if (-not (Test-Path -LiteralPath $inferenceSocket)) {
    Write-Error 'Docker engine is unavailable, but the known dockerInference stale socket was not found.'
}

if (-not $Recover) {
    Write-Error 'Known stale dockerInference socket detected. Re-run with -Recover for the reversible recovery.'
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
