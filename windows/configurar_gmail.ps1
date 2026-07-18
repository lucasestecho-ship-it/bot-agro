$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    py -m venv (Join-Path $ProjectRoot ".venv")
}

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements-gmail.txt")

$ClientJson = Read-Host "Arrastra aqui el JSON OAuth de Google y presiona Enter"
$ClientJson = $ClientJson.Trim('"')
& $VenvPython (Join-Path $PSScriptRoot "configurar_gmail.py") $ClientJson

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo autorizar Gmail."
}

Write-Host "Autorizacion terminada. El archivo para Render quedo en Documents\CapatazCampo."
