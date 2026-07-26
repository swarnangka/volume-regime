"""Validate the engine: hand-built cases first, then a synthetic universe."""
import random, json
from regime_engine import compute_daily, band_for, distribution, percentile_of

random.seed(7)


def bar(d, c, v, o=None, h=None, l=None):
    o = o if o is not None else c
    h = h if h is not None else max(o, c) * 1.01
    l = l if l is not None else min(o, c) * 0.99
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------- band edges
def test_bands():
    cases = [(0.10, "DEAD"), (0.249, "DEAD"), (0.25, "CHOPPY"), (0.49, "CHOPPY"),
             (0.50, "TRADABLE"), (0.69, "TRADABLE"), (0.70, "STRONG"),
             (0.99, "STRONG"), (1.00, "HIGH DEMAND"), (1.67, "HIGH DEMAND"),
             (1.99, "HIGH DEMAND"), (2.00, "EXTREME"), (2.19, "EXTREME")]
    for r, want in cases:
        got = band_for(r)[0]
        assert got == want, f"ratio {r}: expected {want}, got {got}"
    print("PASS  band edges (13 cases)")


# --------------------------------------- reproduce the trader's exact screen
def test_target_reading():
    """
    Build a 40-stock universe engineered to print the reference dashboard:
        5 high-vol, 3 low-vol -> ratio 1.67 -> HIGH DEMAND
        15 up / 25 down, most closing in the lower half -> SHAKEOUT verdict
        2 days in regime, slope rising
    """
    dates = [f"2026-06-{d:02d}" for d in range(1, 29)]
    universe = {}

    for k in range(40):
        sym = f"STK{k:02d}"
        bars = []
        price = 100.0
        for i, d in enumerate(dates):
            base_vol = 1_000_000

            # Quiet baseline, then engineer the last three sessions.
            mult = random.uniform(0.75, 1.15)
            if i >= len(dates) - 3:
                if k < 5:
                    mult = 2.2          # high-volume names
                elif k < 8:
                    mult = 0.35         # dried-up names
                else:
                    mult = 0.9          # everyone else, unremarkable

            # Last 3 days: 15 up / 25 down, and weak closes on the heavy names.
            if i >= len(dates) - 3:
                up = k >= 25
                price = price * (1.012 if up else 0.988)
                if up:
                    o, c = price * 0.995, price
                    h, l = price * 1.004, price * 0.99
                else:
                    o, c = price * 1.01, price
                    h, l = price * 1.015, price * 0.998   # closes near the low
                bars.append(bar(d, c, int(base_vol * mult), o, h, l))
            else:
                price *= random.uniform(0.995, 1.005)
                bars.append(bar(d, price, int(base_vol * mult)))
        universe[sym] = bars

    sessions = compute_daily(universe, {"lookback": 20, "baseline": "mean"})
    last = sessions[-1]

    print(f"      ratio={last['ratio']}  regime={last['regime']}  "
          f"hi={last['n_high']}/{last['n_counted']}  lo={last['n_low']}/{last['n_counted']}")
    print(f"      breadth={last['adv']} up / {last['dec']} dn   "
          f"closes: {last['upper_half']} upper / {last['lower_half']} lower")
    print(f"      slope={last['slope_label']}  days_in_regime={last['days_in_regime']}")
    print(f"      signal={last['signal']}")
    print(f"      verdict={last['verdict']}")

    assert last["n_high"] == 5, last["n_high"]
    assert last["n_low"] == 3, last["n_low"]
    assert abs(last["ratio"] - 1.667) < 0.01
    assert last["regime"] == "HIGH DEMAND"
    assert last["adv"] == 15 and last["dec"] == 25
    assert "SHAKEOUT" in last["verdict"]
    print("PASS  reproduces the reference dashboard exactly")


# ------------------------------------------------------- divergence check
def test_breadth_divergence():
    """The A-vs-B question: on a day where advance/decline and the volume
    counts disagree, the ratio must follow the volume counts."""
    dates = [f"2026-05-{d:02d}" for d in range(1, 29)]
    universe = {}
    for k in range(40):
        sym, bars, price = f"S{k:02d}", [], 100.0
        for i, d in enumerate(dates):
            mult = random.uniform(0.8, 1.1)
            if i == len(dates) - 1:
                mult = 2.5 if k < 4 else (0.3 if k < 13 else 0.95)
            if i == len(dates) - 1:
                price *= 1.01 if k < 30 else 0.99      # 30 up / 10 down
            else:
                price *= random.uniform(0.997, 1.003)
            bars.append(bar(d, price, int(1_000_000 * mult)))
        universe[sym] = bars

    last = compute_daily(universe, {"baseline": "mean"})[-1]
    print(f"      breadth {last['adv']}up/{last['dec']}dn but volume "
          f"{last['n_high']}hi/{last['n_low']}lo -> ratio {last['ratio']}")
    assert last["adv"] == 30 and last["dec"] == 10
    assert last["n_high"] == 4 and last["n_low"] == 9
    assert abs(last["ratio"] - 0.444) < 0.01
    assert last["regime"] == "CHOPPY"
    print("PASS  ratio tracks volume counts, not advance/decline")


# ------------------------------------------------------------ full pipeline
def test_synthetic_history():
    """400 sessions, 150 names, with a regime cycle baked in."""
    dates = [f"D{i:04d}" for i in range(400)]
    universe = {}

    # Market-wide participation as an Ornstein-Uhlenbeck process in log space:
    # mean-reverting around 1.0, with occasional shock days. Volume that simply
    # drifts upward would sit above its own trailing baseline forever and pin
    # the ratio at the cap, which is not how a real tape behaves.
    wave, lvl = [], 0.0
    for i in range(400):
        lvl += -0.06 * lvl + random.gauss(0, 0.075)
        shock = 0.55 if random.random() < 0.02 else 0.0
        wave.append(pow(2.718281828, lvl + shock))

    for k in range(150):
        sym, bars, price = f"N{k:03d}", [], 100.0
        for i, d in enumerate(dates):
            drive = wave[i] * random.lognormvariate(0, 0.62)
            price *= random.uniform(0.985, 1.016)
            o = price * random.uniform(0.995, 1.005)
            h = max(o, price) * random.uniform(1.001, 1.02)
            l = min(o, price) * random.uniform(0.98, 0.999)
            bars.append(bar(d, price, int(1_000_000 * drive), o, h, l))
        universe[sym] = bars

    sessions = compute_daily(universe)
    # exclude_today=True means the first usable bar is index lookback+1
    assert len(sessions) == 400 - 21, len(sessions)
    ratios = [s["ratio"] for s in sessions]
    print(f"      {len(sessions)} sessions  ratio min={min(ratios):.2f} "
          f"max={max(ratios):.2f} median={sorted(ratios)[len(ratios)//2]:.2f}")

    dist = distribution(sessions)
    for d in dist:
        print(f"      {d['band']:<12} {d['days']:>4}d  {d['share']*100:>5.1f}%")

    # persistence must be monotone within a regime run
    runs = 0
    for i in range(1, len(sessions)):
        if sessions[i]["regime"] == sessions[i-1]["regime"]:
            assert sessions[i]["days_in_regime"] == sessions[i-1]["days_in_regime"] + 1
        else:
            assert sessions[i]["days_in_regime"] == 1
            runs += 1
    print(f"PASS  full pipeline, {runs} regime changes, persistence consistent")

    pct = percentile_of(sessions, 1.67)
    print(f"      a 1.67 reading sits at the {pct*100:.0f}th percentile of this sample")
    return sessions


if __name__ == "__main__":
    test_bands()
    test_target_reading()
    test_breadth_divergence()
    s = test_synthetic_history()
    print("\nALL TESTS PASSED")
