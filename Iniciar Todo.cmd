@echo off
setlocal
title Trading Assistant - Todo (Bridge + App)
cd /d "%~dp0"

echo.
echo  ===============================================
echo   Trading Assistant - LANZADOR COMPLETO
echo   - Bridge MT5 (FTMO)  ventana aparte
echo   - Frontend (backend: Render)  http://localhost:3002
echo  ===============================================
echo.

REM ---- Preflight: npm ----
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro npm en el PATH. Instala Node.js desde https://nodejs.org
  pause
  exit /b 1
)

REM ---- Preflight: python + MetaTrader5 ----
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro python en el PATH. Instala Python 3.12 y reintenta.
  pause
  exit /b 1
)
python -c "import MetaTrader5" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] El paquete MetaTrader5 no esta instalado en este python.
  echo Ejecuta:  python -m pip install -r bridge\requirements.txt
  pause
  exit /b 1
)

REM ---- Dependencias frontend (solo primera vez) ----
if not exist "frontend\node_modules\" (
  echo Primera vez: instalando dependencias del frontend...
  pushd frontend
  call npm install
  if errorlevel 1 (
    echo.
    echo [ERROR] Fallo "npm install". Revisa la salida de arriba.
    popd
    pause
    exit /b 1
  )
  popd
)

REM ---- 1) Bridge MT5 en ventana propia (deja el log a la vista) ----
echo Lanzando Bridge MT5 en ventana aparte...
start "Bridge MT5 (FTMO)" cmd /k "cd /d "%~dp0" && python bridge\main.py"

REM ---- 2) Abre el navegador cuando el frontend responda (hasta ~120s) ----
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{$null=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3002' -TimeoutSec 3; Start-Process 'http://localhost:3002'; break}catch{Start-Sleep 1}}"

REM ---- 3) Frontend en esta ventana (bloqueante; Ctrl+C para detener) ----
echo.
echo  El navegador se abrira solo cuando el frontend este listo.
echo  Esta ventana corre el frontend. Cierra la ventana "Bridge MT5" para
echo  detener el bridge por separado.
echo.
cd /d "%~dp0frontend"
call npm run dev

echo.
echo El frontend se ha detenido. (El bridge sigue en su ventana; cierrala aparte.)
pause
