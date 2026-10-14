"""Descarga paginada de OHLC M15 de Twelve Data a CSV local (cache del backtester).

Una petición = 5000 velas = 1 crédito. 2020-07 → hoy ≈ 32 peticiones por par.
Respeta el cap 8 req/min del free tier (9 s entre llamadas). Idempotente: los
tramos ya descargados no se vuelven a pedir.

Uso (desde backend/, con TWELVEDATA_API_KEY en backend/.env):
    python -m scripts.bt_data                       # AUDUSD,USDCAD desde 2020-07-01
    python -m scripts.bt_data --pairs AUDUSD --start 2023-01-01
    python -m scripts.bt_data --interval 5min      # M5 para el replay del marco (~115 peticiones/par)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLEEP = float(os.environ.get("BT_SLEEP", "9"))  # s entre peticiones (subir si el bridge en vivo comparte la key)
CACHE = Path(os.environ.get("BT_CACHE_DIR", ROOT / "scripts" / ".bt_cache"))
CHUNK_DAYS = {"15min": 70, "5min": 20, "1day": 6000}  # < 5000 velas por tramo en días hábiles

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _api_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TWELVEDATA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("TWELVEDATA_API_KEY", "")


def _fetch(pair: str, start: datetime, end: datetime, key: str, interval: str) -> list[dict]:
    qs = urllib.parse.urlencode({
        "symbol": f"{pair[:3]}/{pair[3:]}", "interval": interval, "timezone": "UTC",
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "outputsize": 5000, "order": "ASC", "apikey": key,
    })
    with urllib.request.urlopen(f"https://api.twelvedata.com/time_series?{qs}", timeout=60) as r:
        d = json.load(r)
    if d.get("status") != "ok":
        if "No data is available" in str(d.get("message")):
            return []
        raise RuntimeError(d.get("message"))
    return d["values"]


def _fetch_retry(pair: str, start: datetime, end: datetime, key: str, interval: str) -> list[dict]:
    for _ in range(3):
        try:
            return _fetch(pair, start, end, key, interval)
        except Exception as e:
            print(f"  {pair} {start:%Y-%m-%d}: {e} — reintento en 60 s")
            time.sleep(60)
    raise SystemExit(f"{pair} {start:%Y-%m-%d}: falló 3 veces")


def _dir(pair: str, interval: str) -> Path:
    return CACHE / (pair if interval == "15min" else f"{pair}_{interval}")


def chunk_path(pair: str, start: datetime, interval: str = "15min") -> Path:
    return _dir(pair, interval) / f"{start:%Y%m%d}.csv"


def download(pair: str, start: datetime, end: datetime, key: str, interval: str = "15min") -> None:
    _dir(pair, interval).mkdir(parents=True, exist_ok=True)
    t = start
    while t < end:
        t2 = min(t + timedelta(days=CHUNK_DAYS[interval]), end)
        p = chunk_path(pair, t, interval)
        recent = t2 > datetime.now(timezone.utc) - timedelta(days=2)
        if p.exists() and not recent:
            t = t2
            continue
        vals = _fetch_retry(pair, t, t2, key, interval)
        if len(vals) >= 5000:  # tramo con más velas de las que TD devuelve: partir en dos
            mid = t + (t2 - t) / 2
            time.sleep(SLEEP)
            vals = _fetch_retry(pair, t, mid, key, interval)
            time.sleep(SLEEP)
            seen = {v["datetime"] for v in vals}
            vals += [v for v in _fetch_retry(pair, mid, t2, key, interval) if v["datetime"] not in seen]
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "open", "high", "low", "close"])
            for v in vals:
                w.writerow([v["datetime"], v["open"], v["high"], v["low"], v["close"]])
        print(f"  {pair} {t:%Y-%m-%d} → {t2:%Y-%m-%d}: {len(vals)} velas")
        t = t2
        time.sleep(SLEEP)


def load(pair: str, interval: str = "15min") -> list[tuple[datetime, float, float, float, float]]:
    """Todas las velas cacheadas del par, ordenadas y sin duplicados."""
    bars = {}
    for p in sorted(_dir(pair, interval).glob("*.csv")):
        with p.open() as f:
            for r in csv.DictReader(f):
                t = datetime.fromisoformat(r["ts"]).replace(tzinfo=timezone.utc)
                # TD rellena sábado/domingo desde 2026: el mercado reabre el domingo ~21 UTC
                if t.weekday() == 5 or (t.weekday() == 6 and t.hour < 20):
                    continue
                bars[t] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
    return [(t, *v) for t, v in sorted(bars.items())]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="AUDUSD,USDCAD")
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--interval", default="15min", choices=sorted(CHUNK_DAYS))
    a = ap.parse_args()
    key = _api_key()
    if not key:
        raise SystemExit("Falta TWELVEDATA_API_KEY en backend/.env")
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    for pair in a.pairs.split(","):
        print(f"{pair} {a.interval}: descargando {start:%Y-%m-%d} → {end:%Y-%m-%d} en {CACHE}")
        download(pair, start, end, key, a.interval)
        print(f"{pair}: {len(load(pair, a.interval))} velas {a.interval} en cache")


if __name__ == "__main__":
    main()
