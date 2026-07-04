/** Pares operativos del usuario — badge "Operativo" en el scanner. */
export const WATCHLIST = ["EURUSD"];

/** Pares del playbook + Pine — fuente única para RightBar/A+ y afines.
 *  Antes había 3 listas contradictorias (WATCHLIST, APLUS_PAIRS con majors
 *  que el playbook prohíbe, DEFAULT_PAIRS de zonas). */
export const MY_PAIRS = ["AUDUSD", "USDCAD", "EURUSD"];

/** Polling intervals (ms) */
export const POLL_SIGNALS_MS = 5000;
export const POLL_MARKET_MS = 300000; // 5 min — scanner / radar
