@echo off
chcp 65001 >nul
cd /d "%~dp0"

set DESTINO=%LOCALAPPDATA%\CapatazCampo\runner
set VENV=%DESTINO%\.venv
set PY=%VENV%\Scripts\python.exe
set SCRIPT=%DESTINO%\respaldar_supabase.py

echo ============================================================
echo   Instalando el respaldo diario de la base
echo ============================================================
echo.

echo [1/5] Copiando el script...
if not exist "%DESTINO%" mkdir "%DESTINO%"
copy /Y "windows\respaldar_supabase.py" "%SCRIPT%" >nul
copy /Y "windows\requirements-backup.txt" "%DESTINO%\requirements-backup.txt" >nul
if errorlevel 1 goto error

echo [2/5] Preparando Python...
if not exist "%PY%" py -m venv "%VENV%"
if errorlevel 1 goto error
"%PY%" -m pip install --disable-pip-version-check -q -r "%DESTINO%\requirements-backup.txt"
if errorlevel 1 goto error

echo [3/5] Configurando y programando la tarea diaria...
"%PY%" "%SCRIPT%" --sin-preguntas
if errorlevel 1 goto sinclave

echo.
echo [4/5] Corriendo el primer respaldo...
"%PY%" "%SCRIPT%" --verbose
if errorlevel 1 goto error

echo.
echo [5/5] Verificando...
"%PY%" "%SCRIPT%" --verificar

echo.
echo ============================================================
echo   LISTO. Se va a repetir solo todos los dias a las 21:00.
echo ============================================================
echo.
pause
exit /b 0

:sinclave
echo.
echo ============================================================
echo   FALTA LA CLAVE
echo.
echo   No hay ninguna clave de Capataz Campo guardada en esta PC.
echo   Se pide una sola vez. Abri una terminal y corre:
echo.
echo     "%PY%" "%SCRIPT%" --setup
echo.
echo   Despues volve a hacer doble clic aca.
echo ============================================================
echo.
pause
exit /b 1

:error
echo.
echo ============================================================
echo   ALGO FALLO. Copiale a Claude el texto de arriba.
echo ============================================================
echo.
pause
exit /b 1
