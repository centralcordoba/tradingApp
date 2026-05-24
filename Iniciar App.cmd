@echo off
setlocal
title Trading Assistant
cd /d "%~dp0frontend"

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro npm en el PATH.
  echo Instala Node.js desde https://nodejs.org y vuelve a intentarlo.
  echo.
  pause
  exit /b 1
)

if not exist node_modules\ (
  echo Primera vez: instalando dependencias del frontend...
  call npm install
  if errorlevel 1 (
    echo.
    echo [ERROR] Fallo "npm install". Revisa la salida de arriba.
    pause
    exit /b 1
  )
)

echo.
echo  ===============================================
echo   Trading Assistant - frontend (backend: Render)
echo   URL: http://localhost:3001
echo   El navegador se abrira solo cuando este listo.
echo   Cierra esta ventana (o Ctrl+C) para detenerlo.
echo  ===============================================
echo.

REM Abre el navegador cuando el servidor responda (hasta ~120s, sin bloquear los logs)
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{$null=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3001' -TimeoutSec 3; Start-Process 'http://localhost:3001'; break}catch{Start-Sleep 1}}"

call npm run dev

echo.
echo El servidor se ha detenido.
pause
