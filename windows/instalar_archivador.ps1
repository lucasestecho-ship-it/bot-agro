$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "CapatazCampo\runner"
$VenvDir = Join-Path $InstallDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$InstalledScript = Join-Path $InstallDir "archivar_supabase.py"
$InstalledRequirements = Join-Path $InstallDir "requirements-archiver.txt"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "archivar_supabase.py") $InstalledScript -Force
Copy-Item (Join-Path $PSScriptRoot "requirements-archiver.txt") $InstalledRequirements -Force

if (-not (Test-Path $VenvPython)) {
    py -m venv $VenvDir
}

& $VenvPython -m pip install --disable-pip-version-check -r $InstalledRequirements
& $VenvPython $InstalledScript --setup

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo instalar el archivador."
}

Write-Host ""
Write-Host "Instalacion terminada. Se ejecuta una primera prueba ahora."
& $VenvPython $InstalledScript --verbose
