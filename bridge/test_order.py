"""Test de humo de ejecución real en MT5 — SOLO cuenta demo (bloqueado en real).

Coloca una orden mínima (0.01 lots) con SL/TP lejanos, la muestra, espera unos
segundos para verla en el terminal y la cierra a mercado. El trade cerrado queda
en la pestaña Historial de MT5. Se salta a propósito las guardas del bridge
(ventanas, máx trades): es un test de fontanería, no de estrategia.

Uso:
  python test_order.py                 # BUY 0.01 AUDUSD, cierra tras 30s
  python test_order.py USDCAD          # otro símbolo
  python test_order.py --keep          # deja la posición abierta (cerrar a mano)
  python test_order.py --real          # permitir en cuenta NO demo (peligro)
"""
from __future__ import annotations

import sys
import time

from config import Config
from mt5_client import Mt5Client, mt5

HOLD_SEC = 30
SL_TP_DIST_PCT = 0.5  # distancia del SL/TP: 0.5% del precio (sirve para forex y cripto)


def main() -> int:
    args = sys.argv[1:]
    keep = "--keep" in args
    allow_real = "--real" in args
    symbol = next((a.upper() for a in args if not a.startswith("--")), "AUDUSD")

    if mt5 is None:
        print("Paquete MetaTrader5 no instalado (pip install -r requirements.txt)")
        return 1
    cfg = Config()
    client = Mt5Client(cfg)
    if not client.connect():
        return 1

    info = mt5.account_info()
    if info.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and not allow_real:
        print(f"La cuenta {info.login} ({info.server}) NO es demo — test bloqueado.")
        print("Si de verdad quieres esto en real, relanza con --real.")
        client.shutdown()
        return 1

    broker_symbol = symbol + cfg.symbol_suffix
    specs = client.symbol_specs(broker_symbol)
    if specs is None:
        print(f"Sin especificaciones para {broker_symbol} — ¿símbolo correcto?")
        client.shutdown()
        return 1
    _, _, vol_min, _, _ = specs
    lots = max(0.01, vol_min)

    price = client.current_price(broker_symbol, "LONG")
    if price is None:
        print(f"Sin tick para {broker_symbol} — ¿mercado cerrado?")
        client.shutdown()
        return 1
    si = mt5.symbol_info(broker_symbol)
    dist = price * SL_TP_DIST_PCT / 100.0
    sl = round(price - dist, si.digits)
    tp = round(price + dist, si.digits)

    print(f"Colocando BUY {lots} {broker_symbol} @ ~{price} SL {sl} TP {tp} (magic {cfg.magic})")
    ok, detail, ticket = client.market_order(broker_symbol, "LONG", lots, sl, tp, "test:humo")
    if not ok:
        print(f"FALLO al ejecutar: {detail}")
        client.shutdown()
        return 1
    print(f"EJECUTADA: {detail}")

    time.sleep(1)
    pos = mt5.positions_get(ticket=ticket)
    if pos:
        p = pos[0]
        print(f"Posicion visible en MT5: ticket {p.ticket} vol {p.volume} "
              f"open {p.price_open} SL {p.sl} TP {p.tp} PnL flotante {p.profit:+.2f} USD")
    else:
        print("AVISO: positions_get no la devuelve — revisar el terminal a mano")

    if keep:
        print("--keep: la posicion queda ABIERTA. Cierrala a mano en MT5.")
        client.shutdown()
        return 0

    print(f"Cerrando en {HOLD_SEC}s — mirala en la pestaña 'Operaciones' del terminal...")
    time.sleep(HOLD_SEC)
    tick = mt5.symbol_info_tick(broker_symbol)
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker_symbol,
        "volume": lots,
        "type": mt5.ORDER_TYPE_SELL,
        "position": ticket,
        "price": tick.bid,
        "deviation": 20,
        "magic": cfg.magic,
        "comment": "test:cierre",
    }
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        r = mt5.order_send({**base, "type_filling": filling})
        if r is None:
            print(f"order_send devolvio None: {mt5.last_error()} — cierrala a mano")
            client.shutdown()
            return 1
        if r.retcode == mt5.TRADE_RETCODE_DONE:
            deals = mt5.history_deals_get(position=ticket) or []
            cost = sum(d.profit + d.swap + d.commission for d in deals)
            print(f"CERRADA @ {r.price}. Coste del test: {cost:+.2f} USD. "
                  f"Queda registrada en la pestaña Historial.")
            client.shutdown()
            return 0
        if r.retcode != 10030:  # 10030 = filling no soportado → probar siguiente
            print(f"FALLO al cerrar: retcode {r.retcode} {r.comment} — cierrala a mano")
            client.shutdown()
            return 1
    print("Ningun type_filling aceptado al cerrar — cierrala a mano")
    client.shutdown()
    return 1


if __name__ == "__main__":
    sys.exit(main())
