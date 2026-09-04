$ErrorActionPreference = 'Stop'

$python = if ($env:PYTHON_EXECUTABLE) {
    $env:PYTHON_EXECUTABLE
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

Invoke-Checked { & $python -m ruff check apps packages tests } 'Ruff lint'
Invoke-Checked { & $python -m ruff format --check apps packages tests } 'Ruff format'
Invoke-Checked { & $python -m mypy } 'Mypy'
Invoke-Checked { & $python -m pytest --cov=apps --cov=packages --cov-report=term-missing } 'Pytest'
Invoke-Checked { npm run lint } 'Frontend lint'
Invoke-Checked { npm run test } 'Frontend tests'
Invoke-Checked { npm run build } 'Frontend build'
