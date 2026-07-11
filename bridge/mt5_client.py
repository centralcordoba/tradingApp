"""Wrapper fino sobre el paquete oficial MetaTrader5 (Windows, terminal local).

Si el paquete no está instalado o el terminal no conecta, el bridge puede
seguir en DRY_RUN con especificaciones estáticas aproximadas — pero nunca
ejecutar en real sin conexión verificada.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("bridge.mt5")

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

# Fallback DRY_RUN sin terminal: (tick_value, tick_size, vol_min, vol_max, vol_step)
_STATIC_SPECS = {
    "EURUSD": (1.0, 0.00001, 0.01, 100.0, 0.01),
    "AUDUSD": (1.0, 0.00001, 0.01, 100.0, 0.01),
    "USDCAD": (0.73, 0.00001, 0.01, 100.0, 0.01),  # aprox — depende del CAD/USD
}

_RETCODE_INVALID_FILL = 10030  # type_filling no soportado por el broker


class Mt5Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.connected = False

    def connect(self) -> bool:
        if mt5 is None:
            log.warning("Paquete MetaTrader5 no instalado — modo degradado (solo DRY_RUN)")
            return False
        kwargs = {}
        if self.cfg.mt5_path:
            kwargs["path"] = self.cfg.mt5_path
        if self.cfg.mt5_login:
            kwargs.update(login=self.cfg.mt5_login, password=self.cfg.mt5_password,
                          server=self.cfg.mt5_server)
        if not mt5.initialize(**kwargs):
            log.error("mt5.initialize fallo: %s", mt5.last_error())
            return False
        info = mt5.account_info()
        if info is None:
            log.error("Terminal MT5 abierto pero sin cuenta logueada")
            mt5.shutdown()
            return False
        log.info("Conectado a MT5: cuenta %s (%s) balance %.2f %s",
                 info.login, info.server, info.balance, info.currency)
        self.connected = True
        return True

    def shutdown(self):
        if self.connected and mt5 is not None:
            mt5.shutdown()
            self.connected = False

    def equity(self) -> Optional[float]:
        if not self.connected:
            return None
        info = mt5.account_info()
        return info.equity if info else None

    def symbol_specs(self, symbol: str) -> Optional[tuple]:
        """(tick_value, tick_size, vol_min, vol_max, vol_step) o None."""
        if self.connected:
            si = mt5.symbol_info(symbol)
            if si is not None and not si.visible:
                mt5.symbol_select(symbol, True)
                si = mt5.symbol_info(symbol)
            if si is None:
                return None
            return (si.trade_tick_value, si.trade_tick_size,
                    si.volume_min, si.volume_max, si.volume_step)
        base = symbol.removesuffix(self.cfg.symbol_suffix) if self.cfg.symbol_suffix else symbol
        return _STATIC_SPECS.get(base.upper())

    def current_price(self, symbol: str, side: str) -> Optional[float]:
        if not self.connected:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return tick.ask if side == "LONG" else tick.bid

    def our_positions(self, symbol: str) -> int:
        if not self.connected:
            return 0
        positions = mt5.positions_get(symbol=symbol) or []
        return sum(1 for p in positions if p.magic == self.cfg.magic)

    def pnl_today(self) -> float:
        """PnL de HOY de la cuenta completa (realizado + flotante), aproximando el
        cómputo de FTMO: día que resetea a medianoche Europe/Prague (CE/CEST).
        Cuenta TODA la actividad (también trades manuales) — el límite diario de
        FTMO es de cuenta, no del bot. El dashboard de FTMO es la fuente autoritativa.
        """
        if not self.connected:
            return 0.0
        prague = ZoneInfo("Europe/Prague")
        midnight = datetime.combine(datetime.now(prague).date(), dtime.min, prague)
        deals = mt5.history_deals_get(midnight, datetime.now(timezone.utc) + timedelta(days=1)) or []
        realized = sum(d.profit + d.swap + d.commission for d in deals)
        floating = sum(p.profit for p in (mt5.positions_get() or []))
        return realized + floating

    def market_order(self, symbol: str, side: str, lots: float,
                     sl: float, tp: Optional[float], comment: str) -> tuple:
        """(ok, detalle, position_ticket|None)."""
        if not self.connected:
            return False, "MT5 no conectado", None
        price = self.current_price(symbol, side)
        if price is None:
            return False, f"sin tick para {symbol}", None
        base = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": mt5.ORDER_TYPE_BUY if side == "LONG" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl,
            "deviation": self.cfg.deviation_points,
            "magic": self.cfg.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if tp is not None:
            base["tp"] = tp
        # FTMO suele aceptar IOC; si el broker rechaza el filling se prueban los otros
        for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
            result = mt5.order_send({**base, "type_filling": filling})
            if result is None:
                return False, f"order_send devolvio None: {mt5.last_error()}", None
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return True, f"ticket {result.order} @ {result.price}", result.order
            if result.retcode != _RETCODE_INVALID_FILL:
                return False, f"retcode {result.retcode}: {result.comment}", None
        return False, "ningun type_filling aceptado por el broker", None

    def closed_deals_since(self, since_utc: datetime) -> list:
        """Deals de SALIDA con nuestro magic desde since_utc (para auto-resolución)."""
        if not self.connected:
            return []
        deals = mt5.history_deals_get(since_utc, datetime.now(timezone.utc) + timedelta(days=1)) or []
        return [d for d in deals
                if d.magic == self.cfg.magic and d.entry == mt5.DEAL_ENTRY_OUT]
