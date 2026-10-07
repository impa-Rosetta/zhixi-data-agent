$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) '..\scripts\startup-readiness.psm1'
Import-Module (Resolve-Path $modulePath).Path -Force

function New-ServiceRow {
    param([string]$Name, [string]$State = 'running', [string]$Health = 'healthy', [int]$ExitCode = 0)
    return [pscustomobject]@{ Service = $Name; State = $State; Health = $Health; ExitCode = $ExitCode }
}

function New-HealthyRows {
    $names = @('postgres', 'source-postgres', 'source-mysql', 'redis', 'minio', 'api', 'worker')
    $rows = @($names | ForEach-Object { New-ServiceRow -Name $_ })
    $rows += New-ServiceRow -Name 'scheduler' -Health ''
    $rows += New-ServiceRow -Name 'web' -Health ''
    $rows += New-ServiceRow -Name 'migrate' -State 'exited' -Health ''
    return $rows
}

Describe 'Compose status parsing' {
    It 'accepts a JSON array' {
        $rows = ConvertFrom-ZhixiComposePsJson '[{"Service":"api","State":"running","Health":"healthy"}]'
        @($rows).Count | Should Be 1
        $rows[0].Service | Should Be 'api'
    }

    It 'accepts newline-delimited JSON objects' {
        $raw = '{"Service":"api","State":"running"}' + "`n" + '{"Service":"web","State":"running"}'
        $rows = ConvertFrom-ZhixiComposePsJson $raw
        @($rows).Count | Should Be 2
        $rows[1].Service | Should Be 'web'
    }

    It 'rejects unparseable output instead of treating it as healthy' {
        $threw = $false
        try { $null = ConvertFrom-ZhixiComposePsJson 'not json' }
        catch { $threw = $true }
        $threw | Should Be $true
    }
}

Describe 'Compose readiness' {
    It 'accepts all required healthy services and successful migration' {
        $result = Get-ZhixiComposeReadiness (New-HealthyRows)
        $result.Ready | Should Be $true
        @($result.Issues).Count | Should Be 0
    }

    It 'names a missing service' {
        $rows = @(New-HealthyRows | Where-Object { $_.Service -ne 'worker' })
        $result = Get-ZhixiComposeReadiness $rows
        $result.Ready | Should Be $false
        ($result.Issues -join '; ') | Should Match 'worker.*missing'
    }

    It 'rejects an unhealthy database' {
        $rows = New-HealthyRows
        ($rows | Where-Object Service -eq 'postgres').Health = 'unhealthy'
        $result = Get-ZhixiComposeReadiness $rows
        $result.Ready | Should Be $false
        ($result.Issues -join '; ') | Should Match 'postgres.*unhealthy'
    }

    It 'rejects a failed migration' {
        $rows = New-HealthyRows
        ($rows | Where-Object Service -eq 'migrate').ExitCode = 1
        $result = Get-ZhixiComposeReadiness $rows
        $result.Ready | Should Be $false
        ($result.Issues -join '; ') | Should Match 'migrate.*exit 1'
    }

    It 'requires the API response body to say ok' {
        (Test-ZhixiApiHealthPayload ([pscustomobject]@{ status = 'ok' })) | Should Be $true
        (Test-ZhixiApiHealthPayload ([pscustomobject]@{ status = 'degraded' })) | Should Be $false
        (Test-ZhixiApiHealthPayload $null) | Should Be $false
    }
}

Describe 'Launcher safety boundary' {
    It 'does not invoke Docker recovery automatically' {
        $launcherPath = Join-Path (Split-Path -Parent $PSScriptRoot) '..\scripts\start-zhixi.ps1'
        $launcher = Get-Content (Resolve-Path $launcherPath).Path -Raw
        $launcher | Should Not Match 'docker-preflight\.ps1.*-Recover'
        $launcher | Should Not Match 'wsl(?:\.exe)?.*--terminate'
    }
}
