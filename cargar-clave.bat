@echo off
chcp 65001 >nul
cd /d "%~dp0"

set DESTINO=%LOCALAPPDATA%\CapatazCampo\runner
set VENV=%DESTINO%\.venv
set PY=%VENV%\Scripts\python.exe
set SCRIPT=%DESTINO%\respaldar_supabase.py

echo ============================================================
echo   Guardar la clave de Capataz Campo en esta PC
echo ============================================================
echo.
echo   Se pide una sola vez. Queda guardada en el almacen de
echo   Windows, no en un archivo suelto.
echo.

if not exist "%PY%" (
    echo   Falta preparar el entorno. Corre primero instalar-respaldo.bat
    echo   y despues volve aca.
    echo.
    pause
    exit /b 1
)

copy /Y "windows\respaldar_supabase.py" "%SCRIPT%" >nul

"%PY%" "%SCRIPT%" --cargar-clave
if errorlevel 1 goto error

echo.
echo ============================================================
echo   Listo. Ahora hace doble clic en instalar-respaldo.bat
echo ============================================================
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo   No se guardo la clave. Proba de nuevo.
echo ============================================================
echo.
pause
exit /b 1
