"""Configuración del bridge MT5. Lee bridge/.env (KEY=VALUE) y variables de entorno.

Prioridad: entorno > .env > default. DRY_RUN=1 por defecto — el bridge nunca
envía órdenes reales hasta que se apague explícitamente.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ENV_FILE = Path(__file__).parent / ".env"


def _load_env_file() -> dict:
    if not _ENV_FILE.exists():
        return {}
    out = {}
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


_FILE = _load_env_file()


def _get(key: str, default: str) -> str:
    return os.environ.get(key) or _FILE.get(key) or default


def _parse_windows(raw: str) -> dict:
    # "EURUSD=9-21,AUDUSD=9-14" → {"EURUSD": (9, 21), ...} (hora Madrid, [start, end))
    out = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        sym, rng = part.split("=", 1)
        a, b = rng.split("-", 1)
        out[sym.strip().upper()] = (int(a), int(b))
    return out


@dataclass(frozen=True)
class Config:
    api_base: str = _get("API_BASE", "https://tradingapp-2glz.onrender.com").rstrip("/")
    api_token: str = _get("API_TOKEN", "")   # requerido solo si WEBHOOK_TOKEN está set en Render
    dry_run: bool = _get("DRY_RUN", "1") == "1"
    magic: int = int(_get("MAGIC", "20260711"))

    # Riesgo
    risk_pct: float = float(_get("RISK_PCT", "0.5"))            # % de equity por trade
    max_trades_per_day: int = int(_get("MAX_TRADES_PER_DAY", "2"))
    max_daily_loss_usd: float = float(_get("MAX_DAILY_LOSS_USD", "2500"))
    max_total_loss_usd: float = float(_get("MAX_TOTAL_LOSS_USD", "5000"))
    initial_balance: float = float(_get("INITIAL_BALANCE", "50000"))

    # Qué se opera y cuándo. Solo AUDUSD y USDCAD van a MT5: las señales del Pine
    # (EURUSD) se registran en el log pero NO se ejecutan salvo añadir EURUSD a la
    # whitelist. Ventanas horarias DESACTIVADAS (0-24): sin restricción de sesión
    # — el marco filtra por confluencia, no por hora. Para re-activar una ventana,
    # setear SYMBOL_WINDOWS en el entorno (ej: "AUDUSD=9-14,USDCAD=14-21").
    allowed_symbols: tuple = tuple(
        s.strip().upper()
        for s in _get("ALLOWED_SYMBOLS", "AUDUSD,USDCAD").split(",") if s.strip()
    )
    symbol_windows: dict = field(default_factory=lambda: _parse_windows(
        _get("SYMBOL_WINDOWS", "AUDUSD=0-24,USDCAD=0-24")))

    # Barra mínima del marco para ejecutar: "normal" acepta cualquier OPERAR,
    # "fuerte" solo OPERAR+fuerte. Bajado a "normal" para no exigir lo casi-perfecto.
    marco_min_strength: str = _get("MARCO_MIN_STRENGTH", "normal").strip().lower()
    symbol_suffix: str = _get("SYMBOL_SUFFIX", "")   # brokers con sufijo (EURUSD.r etc.)

    # Ejecución
    deviation_points: int = int(_get("DEVIATION_POINTS", "10"))
    cooldown_min: int = int(_get("COOLDOWN_MIN", "15"))           # por símbolo+lado (marco)
    signal_max_age_min: float = float(_get("SIGNAL_MAX_AGE_MIN", "3"))
    zones_max_age_min: float = float(_get("ZONES_MAX_AGE_MIN", "10"))
    be_threshold_usd: float = float(_get("BE_THRESHOLD_USD", "5"))

    # Cadencias
    zones_poll_sec: int = int(_get("ZONES_POLL_SEC", "300"))
    reporter_poll_sec: int = int(_get("REPORTER_POLL_SEC", "60"))
    manage_poll_sec: int = int(_get("MANAGE_POLL_SEC", "15"))  # gestión parcial/BE del marco

    # MT5 (vacíos = usar la sesión ya logueada en el terminal abierto)
    mt5_login: int = int(_get("MT5_LOGIN", "0"))
    mt5_password: str = _get("MT5_PASSWORD", "")
    mt5_server: str = _get("MT5_SERVER", "")
    mt5_path: str = _get("MT5_PATH", "")
