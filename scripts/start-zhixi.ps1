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
Import-Module (Join-Path $PSScriptRoot 'startup-readiness.psm1') -Force

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

function Invoke-DockerCommand {
    param(
        [string[]]$DockerArguments,
        [int]$TimeoutSeconds,
        [switch]$CaptureOutput
    )

    $command = (Get-Command docker.exe -ErrorAction Stop).Source
    $invocationId = [guid]::NewGuid().ToString('N')
    $stdoutPath = Join-Path $logRoot "docker-$invocationId.stdout.tmp"
    $stderrPath = Join-Path $logRoot "docker-$invocationId.stderr.tmp"
    $process = $null
    try {
        $process = Start-Process -FilePath $command -ArgumentList $DockerArguments `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $nextProgress = (Get-Date).AddSeconds(30)
        while (-not $process.WaitForExit(1000)) {
            if ((Get-Date) -ge $deadline) {
                # Only stop the process tree created by this launcher invocation.
                & taskkill.exe /PID $process.Id /T /F *> $null
                throw "Docker command timed out after $TimeoutSeconds seconds."
            }
            if ((Get-Date) -ge $nextProgress) {
                Write-Status "Docker 命令仍在执行；最长等待 $TimeoutSeconds 秒。"
                $nextProgress = (Get-Date).AddSeconds(30)
            }
        }
        $output = if ($CaptureOutput) { Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $output }
    }
    finally {
        if ($null -ne $process) { $process.Dispose() }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-ApiEndpoint {
    try {
        $payload = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 4
        return (Test-ZhixiApiHealthPayload $payload)
    }
    catch { return $false }
}

function Test-WebEndpoint {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $appUrl -TimeoutSec 4
        return $response.StatusCode -eq 200
    }
    catch { return $false }
}

function Wait-Application {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastIssues = ''
    while ((Get-Date) -lt $deadline) {
        $issues = New-Object System.Collections.Generic.List[string]
        try {
            $status = Invoke-DockerCommand -DockerArguments @('compose', 'ps', '--all', '--format', 'json') -TimeoutSeconds 10 -CaptureOutput
            if ($status.ExitCode -ne 0) { throw "exit $($status.ExitCode)" }
            $rows = @(ConvertFrom-ZhixiComposePsJson $status.Output)
            $readiness = Get-ZhixiComposeReadiness $rows
            foreach ($issue in $readiness.Issues) { $issues.Add($issue) }
        }
        catch { $issues.Add("compose status unavailable: $($_.Exception.Message)") }
        if (-not (Test-ApiEndpoint)) { $issues.Add('api /health: not ready') }
        if (-not (Test-WebEndpoint)) { $issues.Add('web /app: not ready') }

        if ($issues.Count -eq 0) { return [pscustomobject]@{ Ready = $true; Issues = @() } }
        $currentIssues = $issues -join '; '
        if ($currentIssues -ne $lastIssues) {
            Write-Status "等待服务就绪：$currentIssues"
            $lastIssues = $currentIssues
        }
        Start-Sleep -Seconds 3
    }
    return [pscustomobject]@{ Ready = $false; Issues = @($issues.ToArray()) }
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
        if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Write-Status 'Docker Engine 尚未就绪，正在后台启动 Docker Desktop。'
            Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        }
        else {
            Write-Status 'Docker Desktop 已运行，正在等待 Engine 就绪。'
        }
        if (-not (Wait-DockerEngine -TimeoutSeconds 300)) {
            throw 'Docker Engine 在 5 分钟内仍未就绪。请查看 Docker Desktop 错误，运行 scripts/docker-preflight.ps1 做只读预检；启动器不会自动恢复 Docker。'
        }
    }
    Write-Status 'Docker Engine 已就绪。'

    $env:COMPOSE_BAKE = 'false'
    if ($NoBuild) {
        Write-Status '正在启动现有容器，最多等待 5 分钟。'
        $composeResult = Invoke-DockerCommand -DockerArguments @('compose', 'up', '-d') -TimeoutSeconds 300
    }
    else {
        Write-Status '正在构建并启动全部服务，最多等待 20 分钟。'
        $composeResult = Invoke-DockerCommand -DockerArguments @('compose', 'up', '-d', '--build') -TimeoutSeconds 1200
    }
    if ($composeResult.ExitCode -ne 0) {
        $manualCommand = if ($NoBuild) { 'docker compose up -d' } else { 'docker compose up -d --build' }
        throw "Docker Compose 启动失败，退出码：$($composeResult.ExitCode)。请在项目目录手动运行 $manualCommand 查看原始错误；启动器不记录可能含密钥的原始命令输出。"
    }

    Write-Status '容器启动命令已完成，正在核对关键服务、API 和网页。'
    $readiness = Wait-Application -TimeoutSeconds 300
    if (-not $readiness.Ready) {
        throw "服务未在 5 分钟内就绪：$($readiness.Issues -join '; ')。请查看日志：$logPath"
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
