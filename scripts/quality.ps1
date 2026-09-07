$ErrorActionPreference = 'Stop'

$python = if ($env:PYTHON_EXECUTABLE) {
    $env:PYTHON_EXECUTABLE
} elseif (Test-Path (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')) {
    (Resolve-Path (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')).Path
} elseif ($env:VIRTUAL_ENV) {
    Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
} else {
    'python'
}

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Name)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked { & $python scripts/check_secrets.py } 'Secret scan'
Invoke-Checked { & $python -m ruff check apps packages tests scripts } 'Ruff lint'
Invoke-Checked { & $python -m ruff format --check apps packages tests scripts } 'Ruff format'
Invoke-Checked { & $python -m mypy apps packages scripts } 'Mypy'
Invoke-Checked { & $python -m pytest --cov=apps --cov=packages --cov-report=term-missing --cov-fail-under=90 } 'Pytest'
Invoke-Checked { npm run lint } 'Frontend lint'
Invoke-Checked { npm run typecheck } 'Frontend typecheck'
Invoke-Checked { npm run test } 'Frontend tests'
Invoke-Checked { npm run build } 'Frontend build'
