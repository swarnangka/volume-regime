"""
Volume Regime engine.

Implements the breadth-of-volume ratio described in the source framework:

    RVOL(stock, day) = Volume(day) / average Volume over the prior N days
    HIGH-volume stock : RVOL >= 1.5
    LOW-volume  stock : RVOL <  0.5
    RATIO(day)        = count(HIGH) / count(LOW)

The ratio is then banded against the historical distribution, and read
alongside the day's price action (where stocks closed inside their range).

No pandas dependency here on purpose -- the same logic is mirrored in
JavaScript inside the dashboard, and keeping it plain makes the two easy
to cross-check.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# Parameters. Every number here is a modelling choice; change them knowingly.
# ----------------------------------------------------------------------------

DEFAULTS = {
    "lookback": 20,          # sessions in the volume baseline
    "baseline": "median",    # "median" (robust to expiry spikes) or "mean"
    "exclude_today": True,   # keep today's volume out of its own baseline
    "high_mult": 1.5,        # RVOL at or above this = HIGH-volume stock
    "low_mult": 0.5,         # RVOL below this = LOW-volume stock
    "slope_days": 3,         # lookback for the ratio slope
    "slope_dead": 0.05,      # |slope| below this is noise
    "slope_trigger": 0.08,   # |slope| above this is a real move
    "min_low_count": 1,      # floor on the denominator, avoids divide-by-zero
    "ratio_cap": 5.0,        # display cap when the denominator collapses
}

# Band edges, taken from the historical distribution of the ratio.
# (low, high, name, action)
BANDS = [
    (0.00, 0.25, "DEAD",        "Stand aside"),
    (0.25, 0.50, "CHOPPY",      "Selective / favour shorts"),
    (0.50, 0.70, "TRADABLE",    "Breakouts work - trade"),
    (0.70, 1.00, "STRONG",      "Press"),
    (1.00, 2.00, "HIGH DEMAND", "Press, but watch maturity"),
    (2.00, 1e9,  "EXTREME",     "Shakeout - caution"),
]

# Share of all sessions spent in each band, from the 22-year study quoted in
# the source. Used only as a reference line against your own sample.
REFERENCE_FREQ = {
    "DEAD": 0.12,
    "CHOPPY": 0.40,
    "TRADABLE": 0.23,
    "STRONG": 0.12,
    "HIGH DEMAND": 0.10,
    "EXTREME": 0.03,
}

MATURITY_WARN = 15   # sessions above 1.0 after which failure rates climb
MATURITY_HIGH = 25


def band_for(ratio):
    """Return (name, action) for a ratio value."""
    if ratio is None:
        return ("NO DATA", "Insufficient history")
    for lo, hi, name, action in BANDS:
        if lo <= ratio < hi:
            return (name, action)
    return ("EXTREME", "Shakeout - caution")


def _baseline(values, method):
    if not values:
        return None
    if method == "mean":
        return sum(values) / len(values)
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_daily(bars_by_symbol, params=None):
    """
    bars_by_symbol: {symbol: [ {date, open, high, low, close, volume}, ... ]}
                    each list ascending by date.

    Returns a list of per-session dicts, ascending by date.
    """
    p = dict(DEFAULTS)
    if params:
        p.update(params)

    lookback = p["lookback"]
    need = lookback + (1 if p["exclude_today"] else 0)

    # Collect every date present anywhere in the universe.
    all_dates = sorted({b["date"] for bars in bars_by_symbol.values() for b in bars})
    index = {sym: {b["date"]: i for i, b in enumerate(bars)}
             for sym, bars in bars_by_symbol.items()}

    sessions = []
    for date in all_dates:
        n_high = n_low = 0
        n_up = n_down = 0
        n_upper = n_lower = 0
        counted = 0
        high_names, low_names = [], []

        for sym, bars in bars_by_symbol.items():
            i = index[sym].get(date)
            if i is None or i < need:
                continue
            bar = bars[i]
            vol = bar["volume"]
            if not vol or vol <= 0:
                continue

            end = i if p["exclude_today"] else i + 1
            window = [bars[j]["volume"] for j in range(end - lookback, end)
                      if bars[j]["volume"] and bars[j]["volume"] > 0]
            if len(window) < max(5, lookback // 2):
                continue
            base = _baseline(window, p["baseline"])
            if not base or base <= 0:
                continue

            rvol = vol / base
            counted += 1

            if rvol >= p["high_mult"]:
                n_high += 1
                high_names.append({"symbol": sym, "rvol": round(rvol, 2),
                                   "chg": _pct_change(bars, i),
                                   "cpr": _close_position(bar)})
            elif rvol < p["low_mult"]:
                n_low += 1
                low_names.append({"symbol": sym, "rvol": round(rvol, 2),
                                  "chg": _pct_change(bars, i),
                                  "cpr": _close_position(bar)})

            chg = _pct_change(bars, i)
            if chg is not None:
                if chg > 0:
                    n_up += 1
                elif chg < 0:
                    n_down += 1

            cpr = _close_position(bar)
            if cpr is not None:
                if cpr > 0.5:
                    n_upper += 1
                else:
                    n_lower += 1

        if counted == 0:
            continue

        denom = max(n_low, p["min_low_count"])
        ratio = n_high / denom
        capped = ratio > p["ratio_cap"]
        ratio = min(ratio, p["ratio_cap"])

        name, action = band_for(ratio)
        high_names.sort(key=lambda r: -r["rvol"])
        low_names.sort(key=lambda r: r["rvol"])

        sessions.append({
            "date": date,
            "ratio": round(ratio, 3),
            "ratio_capped": capped,
            "regime": name,
            "action": action,
            "n_high": n_high,
            "n_low": n_low,
            "n_counted": counted,
            "adv": n_up,
            "dec": n_down,
            "upper_half": n_upper,
            "lower_half": n_lower,
            "high_names": high_names[:25],
            "low_names": low_names[:25],
        })

    _add_slope_and_persistence(sessions, p)
    for s in sessions:
        s.update(verdict(s, p))
    return sessions


def _pct_change(bars, i):
    if i == 0:
        return None
    prev = bars[i - 1]["close"]
    if not prev:
        return None
    return (bars[i]["close"] - prev) / prev * 100.0


def _close_position(bar):
    """Where the close sat inside the day's range. 1.0 = on the high."""
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return None
    return (bar["close"] - bar["low"]) / rng


def _add_slope_and_persistence(sessions, p):
    n = p["slope_days"]
    for i, s in enumerate(sessions):
        if i >= n:
            slope = s["ratio"] - sessions[i - n]["ratio"]
            s["slope"] = round(slope, 3)
            if slope > p["slope_trigger"]:
                s["slope_label"] = "RISING"
            elif slope < -p["slope_trigger"]:
                s["slope_label"] = "FALLING"
            elif abs(slope) <= p["slope_dead"]:
                s["slope_label"] = "FLAT"
            else:
                s["slope_label"] = "DRIFT UP" if slope > 0 else "DRIFT DOWN"
        else:
            s["slope"] = None
            s["slope_label"] = "-"

        if i == 0 or sessions[i - 1]["regime"] != s["regime"]:
            s["days_in_regime"] = 1
        else:
            s["days_in_regime"] = sessions[i - 1]["days_in_regime"] + 1


def verdict(s, p):
    """
    Reads the ratio against the day's price action. Volume on its own says
    nothing -- the same reading means opposite things depending on whether
    stocks are closing in the upper or lower half of their range.
    """
    ratio = s["ratio"]
    heavy = ratio >= 1.0
    weak_closes = s["lower_half"] > s["upper_half"]
    strong_closes = s["upper_half"] >= s["lower_half"]
    mature = s["days_in_regime"] >= MATURITY_WARN and heavy

    if ratio >= 2.0 and weak_closes:
        return {"signal": "SHAKEOUT - climax selling volume",
                "verdict": "SHAKEOUT - do not chase longs",
                "tone": "danger"}

    if heavy and weak_closes and s["n_high"] >= 3:
        return {"signal": "SHAKEOUT - heavy selling volume",
                "verdict": "SHAKEOUT - selling vol, DON'T chase longs",
                "tone": "danger"}

    if heavy and strong_closes:
        if s["days_in_regime"] >= MATURITY_HIGH:
            return {"signal": "DEMAND - but very extended",
                    "verdict": f"MATURE - {s['days_in_regime']}d elevated, tighten stops",
                    "tone": "warn"}
        if mature:
            return {"signal": "DEMAND - maturing",
                    "verdict": f"PRESS but watch - {s['days_in_regime']}d in regime",
                    "tone": "warn"}
        return {"signal": "GENUINE DEMAND - buyers paying up",
                "verdict": "PRESS - breakouts should hold",
                "tone": "good"}

    # The turn signal: a dead tape lifting for the first time on a green day.
    if ratio < 0.5 and s["slope_label"] == "RISING" and s["adv"] > s["dec"]:
        return {"signal": "FIRST LIFT - participation returning",
                "verdict": "SCALE IN - start with best setups only",
                "tone": "good"}

    if ratio < 0.25:
        return {"signal": "NO PARTICIPATION - tape is dry",
                "verdict": "STAND ASIDE - breakouts will fail",
                "tone": "danger"}

    if ratio < 0.5:
        return {"signal": "CHOPPY - thin participation",
                "verdict": "SELECTIVE - size down, favour shorts",
                "tone": "warn"}

    if ratio < 0.7:
        return {"signal": "TRADABLE - demand building",
                "verdict": "TRADE - breakouts starting to work",
                "tone": "neutral"}

    return {"signal": "STRONG - healthy participation",
            "verdict": "PRESS - conditions are good",
            "tone": "good"}


def distribution(sessions):
    """Share of sessions spent in each band, for the sample supplied."""
    total = len(sessions)
    out = []
    for lo, hi, name, action in BANDS:
        n = sum(1 for s in sessions if s["regime"] == name)
        out.append({
            "band": name,
            "action": action,
            "lo": lo,
            "hi": None if hi > 1e8 else hi,
            "days": n,
            "share": (n / total) if total else 0.0,
            "reference_share": REFERENCE_FREQ.get(name, 0.0),
        })
    return out


def percentile_of(sessions, ratio):
    """Where today's reading sits in the sample's own history."""
    vals = [s["ratio"] for s in sessions]
    if not vals:
        return None
    below = sum(1 for v in vals if v < ratio)
    return below / len(vals)
