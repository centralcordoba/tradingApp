"""Escaneo estrategia × par con validación en holdout (búsqueda de ventaja en otros pares).

PRE-REGISTRO (antes de descargar los pares nuevos):
  Pares: AUDUSD, USDCAD, EURUSD, GBPUSD, USDJPY, XAUUSD, EURJPY (M15 TD, 2020-07 → hoy).
  Estrategias (variante por defecto, reglas en bt_auction / bt_strategies, sin cambios):
    Valentini A, Valentini B, Williams, Crabel, London breakout, Turtle Soup.
  Costes ida y vuelta (aprox. FTMO, bt_sim.COST_PIPS); se imprime también +50%.
  = 42 combinaciones. Con 42 pruebas a este criterio es esperable que 1-2 pasen el
  desarrollo POR AZAR: un aprobado en desarrollo es una CANDIDATA, no un hallazgo.

  Criterio por (estrategia, par) en DESARROLLO 2020-07 → 2025-06: R/trade > 0 en >= 5
  de los 6 años, IC95% bootstrap > 0 y >= +0.10R sobre las entradas aleatorias
  emparejadas. Las candidatas se guardan en .bt_cache/scan_candidates.json.

  HOLDOUT 2025-07 → hoy (--holdout): SOLO las candidatas guardadas, UNA vez. Pasa si
  R/trade > 0 con el coste normal Y con +50% de coste. Se reportan todos los fallos.
  Ojo: el holdout son ~15 meses; para estrategias de baja frecuencia (Turtle Soup
  ~15 trades/año) no puede confirmar nada en ningún sentido.

Uso (desde backend/):
    python -m scripts.bt_scan              # desarrollo → candidatas
    python -m scripts.bt_scan --holdout    # una sola vez
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from scripts import bt_auction, bt_data, bt_strategies
from scripts.bt_sim import COST_PIPS, fmt, summarize

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAIRS = ["AUDUSD", "USDCAD", "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "EURJPY"]
STRATS = [
    ("Valentini A", "auction", ("A", bt_auction.DEFAULT["A"])),
    ("Valentini B", "auction", ("B", bt_auction.DEFAULT["B"])),
    ("Williams", "strat", ("williams", bt_strategies.DEFAULTS["williams"])),
    ("Crabel", "strat", ("crabel", bt_strategies.DEFAULTS["crabel"])),
    ("London breakout", "strat", ("london", bt_strategies.DEFAULTS["london"])),
    ("Turtle Soup", "strat", ("soup", bt_strategies.DEFAULTS["soup"])),
]
CAND = bt_data.CACHE / "scan_candidates.json"


def trades_for(pair: str, holdout: bool) -> dict:
    a = bt_auction.run(pair, holdout)
    s = bt_strategies.run(pair, holdout)
    return {name: (a if src == "auction" else s).get(key, []) for name, src, key in STRATS}


def stats(trades: list[dict], pair: str) -> dict:
    rs = [t["R"] for t in trades]
    hi_cost = [t["R"] - 0.5 * COST_PIPS[pair] / t["risk"] for t in trades]
    s, sr = summarize(rs), summarize([t["rand"] for t in trades if t.get("rand") is not None])
    years = sorted({t["t"].year for t in trades})
    pos = sum(summarize([t["R"] for t in trades if t["t"].year == y])["r"] > 0 for y in years)
    return {"s": s, "hi": summarize(hi_cost), "edge": s.get("r", 0) - (sr.get("r") or 0),
            "pos": pos, "years": len(years)}


def dev(pairs):
    cands = []
    print("══════ DESARROLLO 2020-07 → 2025-06 · R/trade (vs azar) [años+] ══════")
    print(f"  {'':16}" + "".join(f"{p:>22}" for p in pairs))
    table = {p: trades_for(p, False) for p in pairs}
    for name, _, _ in STRATS:
        cells = []
        for p in pairs:
            st = stats(table[p][name], p)
            ok = (st["years"] >= 6 and st["pos"] >= 5 and st["s"].get("lo", -1) > 0 and st["edge"] >= 0.10)
            if ok:
                cands.append({"strategy": name, "pair": p})
            r = st["s"].get("r", 0)
            cells.append(f"{r:+.2f} ({st['edge']:+.2f}) [{st['pos']}/{st['years']}]{'★' if ok else ' '}")
        print(f"  {name:16}" + "".join(f"{c:>22}" for c in cells))
    print(f"\n  ★ = candidata ({len(cands)} de {len(STRATS) * len(pairs)}). Esperables por azar: 1-2.")
    for c in cands:
        st = stats(table[c["pair"]][c["strategy"]], c["pair"])
        print(f"  {c['strategy']} · {c['pair']}: {fmt(st['s'])} · con coste +50%: R/trade {st['hi']['r']:+.3f}")
    CAND.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "candidates": cands,
                                "holdout_run": None}, indent=1), encoding="utf-8")


def holdout():
    if not CAND.exists():
        raise SystemExit("Primero el desarrollo: python -m scripts.bt_scan")
    reg = json.loads(CAND.read_text(encoding="utf-8"))
    if reg.get("holdout_run"):
        print(f"⚠ El holdout ya se corrió el {reg['holdout_run']}: repetirlo no es una prueba nueva.")
    print("══════ HOLDOUT 2025-07 → hoy · solo candidatas del desarrollo ══════")
    if not reg["candidates"]:
        print("  Sin candidatas: nada que validar.")
    cache = {}
    for c in reg["candidates"]:
        p = c["pair"]
        cache.setdefault(p, trades_for(p, True))
        st = stats(cache[p][c["strategy"]], p)
        ok = st["s"].get("r", -1) > 0 and st["hi"].get("r", -1) > 0
        print(f"  {'PASA' if ok else 'FALLA'}  {c['strategy']} · {p}: {fmt(st['s'])} · "
              f"vs azar {st['edge']:+.3f} · coste +50% {st['hi'].get('r', 0):+.3f}")
    reg["holdout_run"] = reg.get("holdout_run") or datetime.now(timezone.utc).isoformat()
    CAND.write_text(json.dumps(reg, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=",".join(PAIRS))
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    holdout() if a.holdout else dev(a.pairs.split(","))


if __name__ == "__main__":
    main()
