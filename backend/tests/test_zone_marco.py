"""Tests del marco teórico de Zonas S/R (gates + confluencia → OPERAR/ESPERAR/NO_OPERAR).

Ejecutables con pytest o como script:
    cd backend && .venv/Scripts/python -m pytest tests/test_zone_marco.py -v
    cd backend && .venv/Scripts/python tests/test_zone_marco.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import zone_signal_engine as zse  # noqa: E402
from app.zone_signal_engine import generate_zone_marco  # noqa: E402


# ─── Factories ──────────────────────────────────────────────────────────────

def _level(price, kind, *, strength=5, touches=4, dist=5.0, wick_ratio=2.0,
           wick_dir="bull", active=True, within=True):
    return {
        "price": price,
        "type": kind,
        "strength": strength,
        "touches": touches,
        "distance_pips": dist,
        "within_range": within,
        "coherent_with_bias": True,
        "active": active,
        "last_touch_wick": (
            {"ratio": wick_ratio, "direction": wick_dir, "top": 0, "bottom": 0, "body": 0}
            if wick_ratio else None
        ),
    }


def _zone_item(*, pair="AUDUSD", price=0.71700, cross_state="A", market_closed=False,
               levels=None, atr_m15=0.0010):
    if levels is None:
        levels = [
            _level(0.71650, "support"),       # mejor nivel LONG, 5 pips abajo
            _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),  # objetivo TP
        ]
    return {
        "pair": pair,
        "price": price,
        "pip_size": 0.0001,
        "levels": levels,
        "market_closed": market_closed,
        "atr_m15": atr_m15,
        "cross": {"state": cross_state},
    }


def _scanner_item(*, side="LONG", confluence=5, extended="normal", rsi=40.0,
                  structure="HH", bloque="1", range_pos=0.3, struct_bullish=True,
                  change_pct=0.1):
    return {
        "side": side,
        "confluence": confluence,
        "extended_status": extended,
        "rsi": rsi,
        "structure": structure,
        "struct_bullish": struct_bullish,
        "bloque": bloque,
        "range_pos": range_pos,
        "change_pct": change_pct,
        "atr": 0.0009,
    }


def setup_function(_):
    # Hora Madrid fija (10h = London, AUDUSD en fire) para determinismo.
    zse._madrid_hour = lambda: 10  # type: ignore[assignment]
    zse._STRENGTH_STATE.clear()


# ─── Casos ──────────────────────────────────────────────────────────────────

def test_operar_tendencia_a_favor():
    m = generate_zone_marco(_zone_item(), _scanner_item())
    assert m["decision"] == "OPERAR"
    assert m["side"] == "LONG"
    assert m["confluence"]["score"] >= 10
    assert m["entry_price"] is not None and m["rrr"] is not None
    assert all(g["passed"] for g in m["gates"] if g["hard"])


def test_no_operar_conflicto_mtf():
    m = generate_zone_marco(_zone_item(cross_state="C"), _scanner_item())
    assert m["decision"] == "NO_OPERAR"
    mtf = next(g for g in m["gates"] if g["key"] == "mtf_coherente")
    assert mtf["passed"] is False


def test_no_operar_scanner_neutral():
    m = generate_zone_marco(_zone_item(cross_state="D"), _scanner_item(side="NEUTRAL"))
    assert m["decision"] == "NO_OPERAR"
    mtf = next(g for g in m["gates"] if g["key"] == "mtf_coherente")
    assert mtf["passed"] is False


def test_no_operar_precio_extendido():
    m = generate_zone_marco(_zone_item(), _scanner_item(extended="skip"))
    assert m["decision"] == "NO_OPERAR"
    ext = next(g for g in m["gates"] if g["key"] == "no_extendido")
    assert ext["passed"] is False


def test_no_operar_mercado_cerrado():
    m = generate_zone_marco(_zone_item(market_closed=True), _scanner_item())
    assert m["decision"] == "NO_OPERAR"
    assert next(g for g in m["gates"] if g["key"] == "mercado_abierto")["passed"] is False


def test_esperar_confluencia_floja():
    # Cross B (fade en rango) evita el veto de estructura; nivel/score mínimos.
    levels = [
        _level(0.71650, "support", strength=2, touches=1, wick_ratio=0),
        _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),
    ]
    m = generate_zone_marco(
        _zone_item(cross_state="B", levels=levels),
        _scanner_item(confluence=3, rsi=50.0, structure="RANGE", bloque="3"),
    )
    assert m["decision"] == "ESPERAR"
    assert m["confluence"]["score"] < zse.PAIR_CONFIG["AUDUSD"]["min_score_normal"]


def test_noticia_degrada_operar_a_esperar():
    base = _zone_item()
    scan = _scanner_item()
    sin = generate_zone_marco(base, scan)
    assert sin["decision"] == "OPERAR"

    con = generate_zone_marco(
        base, scan,
        news_active=True,
        news_event={"title": "US NFP", "minutes_until": 12},
    )
    assert con["decision"] == "ESPERAR"
    assert con["news_warning"] is not None
    assert con["news_warning"]["title"] == "US NFP"
    # La noticia es gate blando: no aparece como fallo duro.
    noticia = next(g for g in con["gates"] if g["key"] == "noticia")
    assert noticia["hard"] is False and noticia["passed"] is False


def test_histeresis_strength_en_frontera():
    # AUDUSD: min_score_strong=10. Un score oscilando 10↔9 no debe hacer
    # flip-flop fuerte↔normal (re-dispararía la alerta sonora en cada poll):
    # una vez fuerte, se mantiene mientras score >= min_strong - 1.
    real = zse._score_signal
    scores = iter([10, 9, 8, 9])
    zse._score_signal = lambda **kw: (next(scores), [], [])  # type: ignore[assignment]
    try:
        args = (_zone_item(), _scanner_item())
        assert generate_zone_marco(*args)["strength"] == "fuerte"   # 10 → entra en fuerte
        assert generate_zone_marco(*args)["strength"] == "fuerte"   # 9 → histéresis: sigue fuerte
        assert generate_zone_marco(*args)["strength"] == "normal"   # 8 → pierde fuerte
        assert generate_zone_marco(*args)["strength"] == "normal"   # 9 sin estado previo → normal
    finally:
        zse._score_signal = real  # type: ignore[assignment]


def test_histeresis_se_resetea_con_gate_duro():
    real = zse._score_signal
    scores = iter([10, 9])
    zse._score_signal = lambda **kw: (next(scores), [], [])  # type: ignore[assignment]
    try:
        assert generate_zone_marco(_zone_item(), _scanner_item())["strength"] == "fuerte"
        # Un gate duro fallado (mercado cerrado) limpia el estado del par...
        m = generate_zone_marco(_zone_item(market_closed=True), _scanner_item())
        assert m["decision"] == "NO_OPERAR"
        # ...así que un 9 posterior ya no hereda el "fuerte".
        assert generate_zone_marco(_zone_item(), _scanner_item())["strength"] == "normal"
    finally:
        zse._score_signal = real  # type: ignore[assignment]


def test_bloque2_en_tendencia_ya_no_veta():
    # Cross A FAVOR + scanner Bloque 2: antes era veto duro (estructura_impulso);
    # ahora el gate pasa — la tendencia de 2 timeframes ya confirma.
    m = generate_zone_marco(_zone_item(), _scanner_item(bloque="2"))
    est = next(g for g in m["gates"] if g["key"] == "estructura_impulso")
    assert est["passed"] is True
    assert m["decision"] in ("OPERAR", "ESPERAR")


def test_nivel_operable_sin_flag_active():
    # Nivel de pullback en tendencia: active=False y fuera del rango de 12p viejo,
    # pero dentro de los 20p nuevos y con fuerza suficiente → ahora es operable.
    levels = [
        _level(0.71550, "support", strength=3, dist=15.0, active=False, within=False),
        _level(0.71900, "resistance", strength=4, dist=20.0, wick_ratio=0),
    ]
    m = generate_zone_marco(_zone_item(levels=levels), _scanner_item())
    nivel = next(g for g in m["gates"] if g["key"] == "nivel_operable")
    # El gate de nivel selecciona el soporte pese a active=False (antes lo excluía).
    assert nivel["passed"] is True
    assert "support 0.7155" in nivel["detail"]


def test_sesion_avoid_no_veta_usdcad():
    # USDCAD a las 10h Madrid (fuera de NY = sesión avoid). Antes era veto duro;
    # ahora la sesión solo puntúa: el gate pasa y es blando.
    m = generate_zone_marco(
        _zone_item(pair="USDCAD", price=1.36000,
                   levels=[_level(1.35950, "support", strength=3, wick_ratio=2.5),
                           _level(1.36300, "resistance", strength=4, dist=30.0, wick_ratio=0)]),
        _scanner_item(),
    )
    ses = next(g for g in m["gates"] if g["key"] == "sesion_operable")
    assert m["session_status"] == "avoid"     # 10h Madrid, fuera de NY
    assert ses["hard"] is False               # ya no es gate duro
    assert not (ses["hard"] and not ses["passed"])  # avoid ya no bloquea
    # La sesión avoid no aparece entre los gates duros que causarían NO_OPERAR.
    hard_blockers = [g["key"] for g in m["gates"] if g["hard"] and not g["passed"]]
    assert "sesion_operable" not in hard_blockers


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        setup_function(fn)
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} tests passed")
