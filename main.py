#!/usr/bin/env python3
"""BTC race bot: Confirmed V-Reversal (V1).

Strategy, decided on each 1-minute bar close, filled at the next bar open:
  entry (flat only, all three must hold):
    DIP    - the lowest low of the last 10 minutes sits at least 72 bps
             below the highest high of the last 60 minutes
    BOUNCE - the latest close has recovered at least 31 bps above that
             10-minute low
    RISING - the last two closes rose in a row
  exit (whole position):
    trailing stop 74 bps below the peak position value since entry, or
    hard stop 150 bps below the entry cost. No take-profit, no max-hold.
  Full size, long only.

Integer arithmetic only (bps via //), no floats, no clock, no randomness,
no network, no files outside the repo. Speaks agent-fun/bars-replay/v1
(hello / batch / done) through the vendored makefun_bars shim, answering
every batch with exactly one reply echoing its seq and its orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10000
DIP_BPS = 72          # dip of the 10-minute low below the 60-minute high
BOUNCE_BPS = 31       # recovery of the close above the 10-minute low
TRAIL_BPS = 74        # trailing stop below the peak value since entry
HARD_STOP_BPS = 150   # hard stop below the entry cost
MAX_SLIPPAGE_BPS = 100

# Bar history, appended once per batch in on_batch (ints, price_scale 5).
_closes = []
_highs = []
_lows = []

# State of the open position: entry cost in quote units (fees included) and
# the highest close seen since entry. Both are 0 while flat; they are
# (re)initialised from the account the first batch that shows a position.
_entry_cost = 0
_peak_close = 0


def _position_value(state, holding):
    """What the holding is worth at the latest close, in quote units."""
    return state.value(SYMBOL, holding.qty)


def on_batch(state, batch):
    """Decide the orders for this bar; [] (or None) means hold."""
    global _entry_cost, _peak_close
    bar = state.latest[SYMBOL]
    close = int(bar["c"])
    _closes.append(close)
    _highs.append(int(bar["h"]))
    _lows.append(int(bar["l"]))

    holding = state.positions.get(SYMBOL)
    if holding is not None:
        if _entry_cost == 0:
            # Position first seen: the buy decided on an earlier bar filled
            # at this bar's open; its cost is the notional spent, fees in.
            _entry_cost = holding.cost
            _peak_close = close
        elif close > _peak_close:
            _peak_close = close
        value = _position_value(state, holding)
        peak_value = holding.qty * _peak_close // 10**7
        if value * BPS <= peak_value * (BPS - TRAIL_BPS):
            # Trailing stop: value fell 70 bps below its peak since entry.
            _entry_cost = 0
            _peak_close = 0
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        if value * BPS <= _entry_cost * (BPS - HARD_STOP_BPS):
            # Hard stop: value fell 150 bps below the entry cost.
            _entry_cost = 0
            _peak_close = 0
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: reset any stale entry state, then test the V-reversal entry.
    _entry_cost = 0
    _peak_close = 0
    if state.warming_up or len(_closes) < 60:
        return []
    high60 = max(_highs[-60:])
    low10 = min(_lows[-10:])
    dip_bps = (high60 - low10) * BPS // high60
    bounce_bps = (close - low10) * BPS // low10
    rising = _closes[-1] > _closes[-2] and _closes[-2] > _closes[-3]
    if dip_bps >= DIP_BPS and bounce_bps >= BOUNCE_BPS and rising:
        # Full size: the whole cash balance, long only.
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    return []


makefun_bars.run(on_batch)
