@echo off
chcp 65001 >nul
cd /d "%~dp0"

for /f "tokens=*" %%b in ('git rev-parse --abbrev-ref HEAD') do set RAMA=%%b

echo ============================================================
echo   Subiendo la rama: %RAMA%
echo ============================================================
echo.

if "%RAMA%"=="main" goto enmain

echo [1/3] Subiendo la rama a GitHub...
git push -u origin %RAMA%
if errorlevel 1 goto error

echo.
echo [2/3] Creando el Pull Request...
gh pr create --fill
if errorlevel 1 goto error

echo.
echo [3/3] Aprobando y mergeando a main...
gh pr merge --squash --delete-branch
if errorlevel 1 goto error

echo.
echo ============================================================
echo   LISTO. Render va a desplegar solo en unos minutos.
echo ============================================================
echo.
pause
exit /b 0

:enmain
echo.
echo   Estas parado en main, no hay ninguna rama nueva para subir.
echo   Nada que hacer.
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo   ALGO FALLO. Copiale a Claude el texto de arriba.
echo.
echo   Causa mas comun: no estas logueado en GitHub.
echo   Se arregla corriendo:  gh auth login
echo ============================================================
echo.
pause
exit /b 1
