# Volume Regime — local dashboard

Tells you which environment the market is in, from free data, running entirely
on your machine.

    RVOL(stock) = today's volume / that stock's own 20-day baseline
    HIGH  = RVOL >= 1.5      LOW = RVOL < 0.5
    RATIO = count(HIGH) / count(LOW)

The ratio is banded, then read against the day's price action.

---

## Run it

```bash
pip install yfinance pandas requests
python fetch_regime.py                 # Nifty 500, 3 years  (~2-4 min)
python -m http.server 8000
```

Open <http://localhost:8000/regime.html>.

Opening `regime.html` straight from disk will not load the data file — browsers
block local file reads. Either serve the folder as above, or drag the JSON onto
the page.

Without a fetch, the page loads `demo_data.json` so you can see the layout.
That data is synthetic. It is not the market.

### Options

```bash
python fetch_regime.py --universe nifty200      # nifty50 | nifty200 | nifty500 | midsmall
python fetch_regime.py --symbols my_list.txt    # one NSE symbol per line
python fetch_regime.py --years 5 --baseline mean
python fetch_regime.py --high 2.0 --low 0.4     # move the thresholds
python fetch_regime.py --csv-out bars.csv       # also dump raw bars
```

Symbol lists come from NSE's published index CSVs, so they stay current. If NSE
is unreachable the script falls back to a built-in 180-name list.

### No Python

Drop a CSV on the page with columns
`date,symbol,open,high,low,close,volume` (many rows per symbol, at least 50
sessions each). Everything is computed in the browser, and the lookback and
threshold controls become live — change them and hit Recalculate.

---

## Reading the screen

**The tape** is drawn as stair-steps, not a line, because that is how the
series actually behaves — it holds a level, then jumps. Amber marks the 3-day
slope window.

**Slope** matters more than level when the tape is dead. A flat 0.25 that lifts
to 0.35 on a green day is the turn signal; the dashboard calls it FIRST LIFT. A
0.38 to 0.35 wobble is noise, and the dead-band ignores it.

**Days in regime** is the maturity clock. Elevated readings that persist 15-25
sessions are where failure rates start climbing, so the verdict downgrades from
PRESS to MATURE on its own.

**The verdict overrides the band.** A high ratio with most stocks closing in the
lower half of their range is selling volume, not demand, so it prints SHAKEOUT
even though the band alone says press. Volume means transactions happened — it
does not say who won.

---

## Two things that will bite you

**1. The bands are universe-dependent.**

The published band table was calibrated on a broad NSE universe of 800+ names,
including many that genuinely go dormant. Run the same thresholds on 40 large
caps and you get a different animal: liquid names rarely drop below 0.5x their
own average, so the denominator stays small and your ratio sits structurally
high. You will read HIGH DEMAND on ordinary Tuesdays.

There is arithmetic behind this. With symmetric noise in log-volume,
P(RVOL < 0.5) = Phi(ln 0.5 / sigma) and P(RVOL > 1.5) = Phi(-ln 1.5 / sigma).
Since |ln 0.5| = 0.69 but ln 1.5 = 0.41, the high threshold sits closer to the
median than the low one. The high tail is mathematically fatter, and the ratio's
natural centre is above 1.0. It only falls below 1.0 when the whole market goes
quiet together — which is exactly what a real drought is.

So use **Calibrate to my universe**. It cuts bands at your own history's 12th,
52nd, 75th, 87th and 97th percentiles — the same boundaries the reference table
uses, measured rather than assumed. If your universe is nothing like the
original, the two views will disagree loudly. That disagreement is information.

**2. Small universes quantise.**

With 40 stocks you might have 5 high and 3 low. The nearby readings are
5/3 = 1.67, 6/3 = 2.00, 5/4 = 1.25 — one stock changing category moves you a
whole band. The dashboard warns when the universe is under 100 names. Use 200+,
or smooth the ratio over 2-3 sessions before banding it.

---

## Data caveats

- Yahoo gives **traded quantity**, not delivery quantity. NSE publishes delivery
  separately, and for a demand-vs-churn read it is the more honest input. Worth
  swapping in if you can source it.
- Splits and bonuses rescale historical volume and wreck the baseline. The
  fetcher drops any symbol with a split inside the working window.
- Expiry days inflate volume. The baseline defaults to **median**, not mean, to
  blunt this. `--baseline mean` matches the original description more literally
  but is more fragile.
- Muhurat and half-days will read as false droughts.
- Yahoo's NSE data is occasionally missing or wrong for illiquid names. The
  fetcher drops symbols with too little history and reports how many.

---

## Files

| | |
|---|---|
| `regime.html` | dashboard, no dependencies, works offline |
| `regime_engine.py` | the calculation |
| `fetch_regime.py` | data fetch, writes `regime_data.json` |
| `make_demo.py` | regenerates the synthetic demo data |
| `test_engine.py` | engine tests |
| `crosscheck.js` | verifies the browser JS matches the Python |

`python test_engine.py` and `node crosscheck.js` both pass; the two engine
implementations agree exactly across 1,287 field comparisons.

---

Everything here is a modelling choice, most of all the 1.5 and 0.5 thresholds
and the band edges. Change them knowingly, and check what the change does to
the historical distribution before trusting the new reading.
