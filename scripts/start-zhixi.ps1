param(
    [switch]$NoBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$projectRoot = Split-Path -Parent $PSScriptRoot
$appDataRoot = Join-Path $env:LOCALAPPDATA 'ZhixiDataAgent'
$logRoot = Join-Path $appDataRoot 'logs'
$logPath = Join-Path $logRoot ('launcher-{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
$appUrl = 'http://127.0.0.1:5173/app'
$apiHealthUrl = 'http://127.0.0.1:8000/health'
$dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
$mutex = New-Object System.Threading.Mutex($false, 'Local\ZhixiDataAgentLauncher')
$hasLock = $false

function Write-Status {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Test-DockerEngine {
    $process = $null
    try {
        $dockerCommand = (Get-Command docker.exe -ErrorAction Stop).Source
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $dockerCommand
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

function Wait-DockerEngine {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Test-HttpEndpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-Application {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Test-HttpEndpoint $apiHealthUrl) -and (Test-HttpEndpoint $appUrl)) {
            return $true
        }
        Start-Sleep -Seconds 3
    }
    return $false
}

try {
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-Status '智析 Data Agent 正在由另一个启动器启动，请稍候。'
        exit 0
    }

    Write-Status '开始启动智析 Data Agent。'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未找到 Docker 命令。请先安装 Docker Desktop。'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'compose.yaml'))) {
        throw "项目目录不完整：$projectRoot"
    }

    if (-not (Test-DockerEngine)) {
        if (-not (Test-Path -LiteralPath $dockerDesktop)) {
            throw "未找到 Docker Desktop：$dockerDesktop"
        }
        Write-Status 'Docker Engine 尚未就绪，正在后台启动 Docker Desktop。'
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        if (-not (Wait-DockerEngine -TimeoutSeconds 120)) {
            $dockerRun = Join-Path $env:LOCALAPPDATA 'Docker\run'
            $knownSockets = @(
                (Join-Path $dockerRun 'dockerInference'),
                (Join-Path $dockerRun 'userAnalyticsOtlpHttp.sock')
            )
            if ($knownSockets | Where-Object { Test-Path -LiteralPath $_ }) {
                Write-Status '检测到已知 Docker 临时套接字故障，正在执行可恢复修复。'
                & (Join-Path $PSScriptRoot 'docker-preflight.ps1') -Recover
            }
            if (-not (Wait-DockerEngine -TimeoutSeconds 180)) {
                throw 'Docker Engine 在 5 分钟内仍未就绪。请打开 Docker Desktop 查看错误详情。'
            }
        }
    }
    Write-Status 'Docker Engine 已就绪。'

    Push-Location $projectRoot
    try {
        $env:COMPOSE_BAKE = 'false'
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            if ($NoBuild) {
                Write-Status '正在启动现有容器。'
                cmd.exe /d /c "docker compose up -d 2>&1" | Tee-Object -FilePath $logPath -Append
            }
            else {
                Write-Status '正在构建并启动全部服务，首次运行可能需要几分钟。'
                cmd.exe /d /c "docker compose up -d --build 2>&1" | Tee-Object -FilePath $logPath -Append
            }
            $composeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($composeExitCode -ne 0) {
            throw "Docker Compose 启动失败，退出码：$composeExitCode"
        }
    }
    finally {
        Pop-Location
    }

    Write-Status '服务已启动，正在等待 API 和网页健康检查。'
    if (-not (Wait-Application -TimeoutSeconds 180)) {
        throw "服务未在 3 分钟内通过健康检查。请查看日志：$logPath"
    }
    Write-Status '智析 Data Agent 已就绪。'

    if (-not $NoBrowser) {
        Start-Process $appUrl
        Write-Status "已打开：$appUrl"
    }
    exit 0
}
catch {
    $message = $_.Exception.Message
    try { Write-Status "启动失败：$message" } catch { Write-Error $message }
    Write-Host ''
    Write-Host "详细日志：$logPath" -ForegroundColor Yellow
    exit 1
}
finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
