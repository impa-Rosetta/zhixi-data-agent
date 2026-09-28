param(
    [string]$OutputDirectory = "output/初赛代码包"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot
$revision = (& git -c "safe.directory=$repoRoot" rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "无法确定 Git 提交号。"
}
$shortRevision = $revision.Substring(0, 7)
$targetDirectory = Join-Path $repoRoot $OutputDirectory
$resolvedParent = [IO.Path]::GetFullPath($targetDirectory)
if (-not $resolvedParent.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "输出位置必须在项目目录内。"
}
New-Item -ItemType Directory -Path $resolvedParent -Force | Out-Null
$archive = Join-Path $resolvedParent "智析DataAgent_A07_初赛源码与关键文档_$shortRevision.zip"
if (Test-Path -LiteralPath $archive) {
    throw "目标压缩包已存在，不覆盖：$archive"
}

# Deliberately use the committed tree. Local .env, database state, caches and
# unrelated uncommitted edits are never read by git archive.
$paths = @(
    ".github", ".dockerignore", ".env.example", ".gitignore",
    "README.md", "启动智析DataAgent.cmd", "alembic.ini", "compose.yaml",
    "package.json", "package-lock.json", "playwright.config.ts", "pyproject.toml", "uv.lock",
    "apps", "packages", "infra", "scripts", "tests", "evaluations",
    "docs/submission/初赛代码包说明_2026-09-28.md",
    "docs/project-status.md", "docs/decisions/README.md",
    "docs/superpowers/specs/2026-09-04-a07-data-agent-design.md",
    "docs/superpowers/specs/2026-09-28-advanced-analysis-modeling-design.md",
    "docs/plans/2026-09-28-advanced-analysis-modeling-implementation-plan.md",
    "docs/acceptance/ADV-A4-real-stack-browser-2026-09-28.md",
    "docs/acceptance/ADV-B1-model-contracts-2026-09-28.md",
    "docs/acceptance/M7.7-D6-current-source-stack-acceptance.md",
    "docs/acceptance/M8-E3e-real-persisted-history-2026-09-28.md",
    "docs/runbooks/docker-desktop-recovery.md"
)
& git -c "safe.directory=$repoRoot" archive --format=zip "--output=$archive" HEAD -- $paths
if ($LASTEXITCODE -ne 0) {
    throw "Git 归档失败。"
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $entries = @($zip.Entries | Where-Object { $_.Name })
    $names = @($entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    $required = @(
        "README.md", "compose.yaml", "pyproject.toml", "uv.lock",
        "docs/submission/初赛代码包说明_2026-09-28.md",
        "docs/project-status.md", "packages/modeling/contracts.py"
    )
    foreach ($item in $required) {
        if ($names -cnotcontains $item) { throw "压缩包缺少：$item" }
    }
    foreach ($name in $names) {
        if ($name -match '(^|/)(\.env|node_modules|\.venv|__pycache__|output|tmp|\.git)(/|$)' -and $name -ne '.env.example') {
            throw "压缩包包含不允许的路径：$name"
        }
        if ($name -match '\.(?:pyc|db|sqlite|log)$') {
            throw "压缩包包含本地数据或缓存：$name"
        }
    }
} finally {
    $zip.Dispose()
}
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "提交号：$revision"
Write-Output "压缩包：$archive"
Write-Output "文件数：$($entries.Count)"
Write-Output "大小：$((Get-Item -LiteralPath $archive).Length) 字节"
Write-Output "SHA256：$digest"
