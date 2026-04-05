$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $PSScriptRoot
$VenvDir = if ($env:VENV_DIR) { $env:VENV_DIR } else { Join-Path $RootDir '.venv' }
$TestTargets = if ($args.Count -gt 0) { $args } else { @('tests') }

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = @('py', '-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = @('python')
} else {
    throw 'No suitable Python interpreter found (py/python).'
}

if (-not (Test-Path $VenvDir)) {
    & $PythonCmd[0] $PythonCmd[1..($PythonCmd.Count - 1)] -m venv $VenvDir
}

$ActivatePath = Join-Path $VenvDir 'Scripts\Activate.ps1'
if (-not (Test-Path $ActivatePath)) {
    throw "Virtual environment activate script not found in $VenvDir."
}

. $ActivatePath
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

$env:PYTHONPATH = if ($env:PYTHONPATH) { "$RootDir\src;$env:PYTHONPATH" } else { "$RootDir\src" }
Set-Location $RootDir
python -m pytest $TestTargets
