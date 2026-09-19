param([switch]$Recover)

$ErrorActionPreference = 'Stop'
$dockerRun = Join-Path $env:LOCALAPPDATA 'Docker\run'
$knownStaleSockets = @(
    (Join-Path $dockerRun 'dockerInference'),
    (Join-Path $dockerRun 'userAnalyticsOtlpHttp.sock')
)

function Test-DockerEngine {
    $process = $null
    try {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = (Get-Command docker.exe -ErrorAction Stop).Source
        $startInfo.Arguments = 'version --format "{{.Server.Version}}"'
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        [void]$process.Start()
        if (-not $process.WaitForExit(5000)) {
            $process.Kill()
            return $false
        }
        return $process.ExitCode -eq 0
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $process) { $process.Dispose() }
    }
}

if (Test-DockerEngine) {
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
