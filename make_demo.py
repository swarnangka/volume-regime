"""Build demo_data.json: synthetic but market-shaped, so the dashboard has
something to render before the first live fetch. Not real prices."""
import json, random, math
from datetime import date, timedelta
from regime_engine import compute_daily, distribution, percentile_of, DEFAULTS, BANDS

random.seed(20260725)

N_STOCKS, N_DAYS = 220, 420

# Trading calendar, weekdays only.
dates, d = [], date(2024, 11, 1)
while len(dates) < N_DAYS:
    if d.weekday() < 5:
        dates.append(d.isoformat())
    d += timedelta(days=1)

# Market participation: slow AR(1) cycle plus event spikes.
market, lvl, spike = [], 0.0, 0.0
for i in range(N_DAYS):
    # Droughts are long and deep; surges are sharp and short-lived. That
    # asymmetry is what pulls the ratio's centre below 1.0 in real data.
    lvl += -0.018 * lvl + random.gauss(-0.004, 0.085)
    spike = spike * 0.45 if spike > 0.05 else 0.0
    if random.random() < 0.02:
        spike = random.uniform(0.8, 1.4)
    market.append(math.exp(lvl + spike))

# Market return, correlated with participation spikes (heavy days skew down).
mret = []
for i in range(N_DAYS):
    drift = random.gauss(0.0004, 0.008)
    if market[i] > 1.6:
        drift -= 0.012
    mret.append(drift)

universe = {}
for k in range(N_STOCKS):
    sym = f"DEMO{k:03d}"
    beta = random.uniform(0.8, 1.9)
    liq = random.lognormvariate(0, 0.8)     # persistent per-stock activity
    act, price, bars = 0.0, random.uniform(80, 900), []
    for i, dt in enumerate(dates):
        # Per-stock volume: persistent idle spells plus market factor.
        act += -0.12 * act + random.gauss(0, 0.30)
        vol = 500_000 * liq * market[i] ** beta * math.exp(act)

        r = mret[i] * beta + random.gauss(0, 0.016)
        prev = price
        price = max(1.0, price * (1 + r))
        o = prev * (1 + random.gauss(0, 0.004))
        hi = max(o, price) * (1 + abs(random.gauss(0, 0.006)))
        lo = min(o, price) * (1 - abs(random.gauss(0, 0.006)))
        bars.append({"date": dt, "open": o, "high": hi, "low": lo,
                     "close": price, "volume": max(1000.0, vol)})
    universe[sym] = bars

sessions = compute_daily(universe)
dist = distribution(sessions)
kept = sessions[-400:]
for s in kept[:-15]:
    s.pop("high_names", None)
    s.pop("low_names", None)

cur = sessions[-1]
payload = {
    "meta": {
        "generated_at": "demo",
        "universe": "DEMO - synthetic data, not real prices",
        "symbols_used": N_STOCKS,
        "sessions_total": len(sessions),
        "params": DEFAULTS,
        "source": "Synthetic demo data",
        "is_demo": True,
    },
    "bands": [{"lo": lo, "hi": (None if hi > 1e8 else hi), "name": n, "action": a}
              for lo, hi, n, a in BANDS],
    "distribution": dist,
    "sessions": kept,
    "current": cur,
    "percentile": percentile_of(sessions, cur["ratio"]),
}
with open("demo_data.json", "w") as f:
    json.dump(payload, f, separators=(",", ":"))

print(f"demo_data.json  {len(sessions)} sessions, {N_STOCKS} stocks")
for x in dist:
    print(f"  {x['band']:<12} {x['days']:>4}d {x['share']*100:>5.1f}%  "
          f"(reference {x['reference_share']*100:>4.0f}%)")
print(f"current: {cur['date']} ratio={cur['ratio']} {cur['regime']} "
      f"{cur['slope_label']} day{cur['days_in_regime']}")
print(f"  {cur['verdict']}")
