Set-StrictMode -Version Latest

function ConvertFrom-ZhixiComposePsJson {
    param([Parameter(Mandatory)][string]$Json)

    $trimmed = $Json.Trim()
    if (-not $trimmed) { throw 'Docker Compose returned empty service status.' }

    try {
        $parsed = ConvertFrom-Json -InputObject $trimmed -ErrorAction Stop
        $rows = @($parsed)
    }
    catch {
        $rows = @()
        foreach ($line in ($trimmed -split "`r?`n")) {
            if (-not $line.Trim()) { continue }
            try {
                $rows += ConvertFrom-Json -InputObject $line -ErrorAction Stop
            }
            catch {
                throw 'Docker Compose service status is not valid JSON.'
            }
        }
    }

    if ($rows.Count -eq 0) { throw 'Docker Compose returned no service status.' }
    foreach ($row in $rows) {
        if ($null -eq $row -or -not $row.PSObject.Properties['Service'] -or -not $row.PSObject.Properties['State']) {
            throw 'Docker Compose service status is missing Service or State.'
        }
    }
    return $rows
}

function Get-ZhixiComposeReadiness {
    param([Parameter(Mandatory)][object[]]$Rows)

    $issues = New-Object System.Collections.Generic.List[string]
    $healthyServices = @('postgres', 'source-postgres', 'source-mysql', 'redis', 'minio', 'api', 'worker')
    $runningServices = @('scheduler', 'web')

    foreach ($name in $healthyServices + $runningServices) {
        $matches = @($Rows | Where-Object { $_.Service -eq $name })
        if ($matches.Count -eq 0) {
            $issues.Add("${name}: missing")
            continue
        }
        foreach ($service in $matches) {
            if ($service.State -ne 'running') {
                $issues.Add("${name}: state $($service.State)")
            }
            elseif ($name -in $healthyServices -and $service.Health -ne 'healthy') {
                $health = if ($service.Health) { $service.Health } else { 'unknown' }
                $issues.Add("${name}: health $health")
            }
        }
    }

    $migrations = @($Rows | Where-Object { $_.Service -eq 'migrate' })
    if ($migrations.Count -eq 0) {
        $issues.Add('migrate: missing')
    }
    else {
        foreach ($migration in $migrations) {
            if ($migration.State -ne 'exited' -or $migration.ExitCode -ne 0) {
                $issues.Add("migrate: state $($migration.State), exit $($migration.ExitCode)")
            }
        }
    }

    return [pscustomobject]@{ Ready = ($issues.Count -eq 0); Issues = @($issues.ToArray()) }
}

function Test-ZhixiApiHealthPayload {
    param($Payload)
    return ($null -ne $Payload -and $Payload.PSObject.Properties['status'] -and $Payload.status -eq 'ok')
}

Export-ModuleMember -Function ConvertFrom-ZhixiComposePsJson, Get-ZhixiComposeReadiness, Test-ZhixiApiHealthPayload
