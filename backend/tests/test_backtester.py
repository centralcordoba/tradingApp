from datetime import datetime, timedelta, timezone

from scripts.bt_auction import day_profile, leg_lvn
from scripts.bt_sim import day_end, r_multiple, sim

PIP = 0.0001
T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def _bars(hlc):
    return [(T0 + timedelta(minutes=15 * i), c, h, l, c) for i, (h, l, c) in enumerate(hlc)]


def test_sim_sl_gana_si_la_vela_toca_ambos():
    bars = _bars([(1.0030, 0.9970, 1.0)])
    assert sim(bars, 0, "LONG", 1.0, 0.9980, 1.0020, day_end(T0), PIP)[2] == "SL"


def test_sim_tp_y_cierre_fin_de_dia():
    bars = _bars([(1.0005, 0.9995, 1.0), (1.0025, 1.0, 1.002)])
    p, _, out = sim(bars, 0, "SHORT", 1.0, 1.0020, 0.9980, day_end(T0), PIP)
    assert out == "SL" and round(p, 1) == -20
    p, _, out = sim(bars[:1], 0, "LONG", 1.0, 0.9980, 1.0040, day_end(T0), PIP)
    assert out == "EOD" and round(p, 6) == 0


def test_day_end_es_las_22_utc_siguientes():
    assert day_end(T0) == T0.replace(hour=22)
    assert day_end(T0.replace(hour=22)) == T0.replace(hour=22) + timedelta(days=1)


def test_r_multiple_descuenta_coste():
    assert r_multiple(24, 12, 1.4) == (24 - 1.4) / 12


def test_profile_poc_en_la_zona_mas_visitada():
    bars = _bars([(1.0010, 1.0000, 1.0005)] * 10 + [(1.0050, 1.0040, 1.0045)])
    prof = day_profile(bars, PIP)
    assert 1.0000 <= prof["poc"] <= 1.0011
    assert prof["val"] <= prof["poc"] <= prof["vah"]
    assert prof["vah"] < 1.0040  # el pico aislado queda fuera del 70%


def test_lvn_cae_en_el_hueco_del_impulso():
    # base densa abajo, hueco rápido en el medio, base densa arriba
    bars = _bars([(1.0010, 1.0000, 1.0005)] * 6 + [(1.0090, 1.0010, 1.0090)]
                 + [(1.0100, 1.0090, 1.0095)] * 6)
    lvn = leg_lvn(bars, PIP)
    assert 1.0020 <= lvn <= 1.0080
