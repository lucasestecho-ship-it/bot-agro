$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "CapatazCampo\runner"
$VenvDir = Join-Path $InstallDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$InstalledScript = Join-Path $InstallDir "respaldar_supabase.py"
$InstalledRequirements = Join-Path $InstallDir "requirements-backup.txt"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "respaldar_supabase.py") $InstalledScript -Force
Copy-Item (Join-Path $PSScriptRoot "requirements-backup.txt") $InstalledRequirements -Force

if (-not (Test-Path $VenvPython)) {
    py -m venv $VenvDir
}

& $VenvPython -m pip install --disable-pip-version-check -r $InstalledRequirements
& $VenvPython $InstalledScript --setup

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo instalar el respaldo."
}

Write-Host ""
Write-Host "Instalacion terminada. Se corre un primer respaldo ahora."
& $VenvPython $InstalledScript --verbose

Write-Host ""
Write-Host "Verificacion:"
& $VenvPython $InstalledScript --verificar
