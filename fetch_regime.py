#!/usr/bin/env python3
"""
Fetch free NSE data, compute the volume regime, write regime_data.json.

Usage
-----
    python fetch_regime.py                      # Nifty 500, 2 years
    python fetch_regime.py --universe nifty200
    python fetch_regime.py --symbols my.txt     # one symbol per line
    python fetch_regime.py --years 5 --baseline mean
    python fetch_regime.py --csv-out bars.csv   # also dump raw bars

Data source is Yahoo Finance via yfinance (free, no key). Symbol lists come
from NSE's own published index CSVs, with an offline fallback.
"""

import argparse, json, sys, time, io, csv
from datetime import datetime, timezone

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    sys.exit("Install dependencies first:  pip install yfinance pandas")

from regime_engine import compute_daily, distribution, percentile_of, DEFAULTS, BANDS

NSE_INDEX_CSV = {
    "nifty50":    "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty200":   "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500":   "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "midsmall":   "https://nsearchives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
}

# Offline fallback, used only if NSE is unreachable. Deliberately broad.
FALLBACK = """
RELIANCE TCS HDFCBANK ICICIBANK INFY HINDUNILVR ITC SBIN BHARTIARTL KOTAKBANK
LT AXISBANK ASIANPAINT MARUTI SUNPHARMA TITAN ULTRACEMCO BAJFINANCE NESTLEIND WIPRO
ONGC NTPC POWERGRID TATAMOTORS TATASTEEL JSWSTEEL HINDALCO COALINDIA GRASIM ADANIENT
ADANIPORTS BAJAJFINSV TECHM HCLTECH DRREDDY CIPLA DIVISLAB BRITANNIA EICHERMOT HEROMOTOCO
BAJAJ-AUTO SHRIRAMFIN APOLLOHOSP TATACONSUM INDUSINDBK SBILIFE HDFCLIFE BPCL IOC GAIL
DABUR GODREJCP MARICO PIDILITIND BERGEPAINT COLPAL MCDOWELL-N UBL PGHH GILLETTE
AMBUJACEM ACC SHREECEM DALBHARAT JKCEMENT RAMCOCEM VEDL NATIONALUM SAIL JINDALSTEL
DLF GODREJPROP OBEROIRLTY PRESTIGE PHOENIXLTD BRIGADE SOBHA LODHA NBCC IRB
PNB BANKBARODA CANBK UNIONBANK IDFCFIRSTB FEDERALBNK BANDHANBNK AUBANK RBLBANK YESBANK
LICHSGFIN CHOLAFIN MUTHOOTFIN MANAPPURAM PFC RECLTD IRFC HUDCO SBICARD ICICIGI
PIIND UPL COROMANDEL CHAMBLFERT DEEPAKNTR SRF AARTIIND ATUL NAVINFLUOR TATACHEM
LUPIN AUROPHARMA TORNTPHARM ALKEM ZYDUSLIFE GLENMARK IPCALAB ABBOTINDIA BIOCON LAURUSLABS
MOTHERSON BOSCHLTD BALKRISIND MRF APOLLOTYRE EXIDEIND TVSMOTOR ASHOKLEY ESCORTS BHARATFORG
LTIM PERSISTENT COFORGE MPHASIS OFSS TATAELXSI KPITTECH CYIENT ZENSARTECH BIRLASOFT
SIEMENS ABB HAVELLS POLYCAB CROMPTON VOLTAS BLUESTARCO THERMAX CUMMINSIND AIAENG
BEL HAL BDL MAZDOCK COCHINSHIP GRSE DATAPATTNS PARAS ASTRAL SUPREMEIND
INDIGO IRCTC CONCOR GMRINFRA ADANIPOWER TATAPOWER JSWENERGY NHPC SJVN TORNTPOWER
ZOMATO NYKAA PAYTM POLICYBZR DMART TRENT ABFRL VBL JUBLFOOD DEVYANI
"""


def load_symbols(args):
    if args.symbols:
        with open(args.symbols) as f:
            syms = [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
        print(f"  {len(syms)} symbols from {args.symbols}")
        return syms

    url = NSE_INDEX_CSV.get(args.universe)
    if url:
        try:
            import requests
            r = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*",
                "Referer": "https://www.nseindia.com/"})
            r.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(r.text)))
            syms = [row["Symbol"].strip().upper() for row in rows if row.get("Symbol")]
            if syms:
                print(f"  {len(syms)} symbols from NSE {args.universe} list")
                return syms
        except Exception as e:
            print(f"  NSE list unavailable ({e.__class__.__name__}), using fallback")

    syms = FALLBACK.split()
    print(f"  {len(syms)} symbols from offline fallback list")
    return syms


def download(symbols, years, batch=60):
    """Batched download. Returns {symbol: [bar, ...]} ascending by date."""
    tickers = [s if s.endswith(".NS") else s + ".NS" for s in symbols]
    frames = {}
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        print(f"  downloading {i+1}-{min(i+batch, len(tickers))} of {len(tickers)} ...")
        try:
            df = yf.download(chunk, period=f"{years}y", interval="1d",
                             group_by="ticker", auto_adjust=False, actions=True,
                             progress=False, threads=True)
        except Exception as e:
            print(f"    batch failed: {e}")
            continue
        for t in chunk:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                if sub is None or sub.empty:
                    continue
                frames[t] = sub
            except Exception:
                continue
        time.sleep(0.4)          # be polite to the endpoint
    return frames


def to_bars(frames, lookback):
    """Convert frames to plain bars, dropping symbols with a split in-window."""
    out, skipped_split, skipped_thin = {}, 0, 0
    for ticker, df in frames.items():
        sym = ticker.replace(".NS", "")
        need = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in need):
            continue
        d = df.dropna(subset=["Close", "Volume"])
        if len(d) < lookback + 30:
            skipped_thin += 1
            continue

        # A split rescales historical volume and wrecks the baseline. If one
        # happened inside the working window, the symbol is untrustworthy.
        if "Stock Splits" in d.columns:
            recent = d["Stock Splits"].tail(lookback + 5)
            if (recent.fillna(0) != 0).any():
                skipped_split += 1
                continue

        bars = []
        for ts, row in d.iterrows():
            v = row["Volume"]
            if pd.isna(v) or v <= 0:
                continue
            bars.append({
                "date": ts.strftime("%Y-%m-%d"),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": float(v),
            })
        if len(bars) >= lookback + 30:
            out[sym] = bars
    print(f"  usable: {len(out)} symbols "
          f"({skipped_split} dropped for splits, {skipped_thin} too short)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="nifty500", choices=list(NSE_INDEX_CSV))
    ap.add_argument("--symbols", help="file with one NSE symbol per line")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=DEFAULTS["lookback"])
    ap.add_argument("--baseline", default=DEFAULTS["baseline"], choices=["median", "mean"])
    ap.add_argument("--high", type=float, default=DEFAULTS["high_mult"])
    ap.add_argument("--low", type=float, default=DEFAULTS["low_mult"])
    ap.add_argument("--out", default="regime_data.json")
    ap.add_argument("--csv-out", help="also write raw bars as long-format CSV")
    ap.add_argument("--keep", type=int, default=500, help="sessions to keep in output")
    args = ap.parse_args()

    print("Volume Regime -- data fetch")
    symbols = load_symbols(args)
    frames = download(symbols, args.years)
    if not frames:
        sys.exit("No data returned. Check your internet connection and try again.")
    bars = to_bars(frames, args.lookback)
    if len(bars) < 20:
        sys.exit(f"Only {len(bars)} usable symbols -- too few to compute breadth.")

    params = {"lookback": args.lookback, "baseline": args.baseline,
              "high_mult": args.high, "low_mult": args.low}
    print("  computing regime ...")
    sessions = compute_daily(bars, params)
    if not sessions:
        sys.exit("No sessions computed -- not enough overlapping history.")

    dist = distribution(sessions)
    kept = sessions[-args.keep:]
    # Constituent detail is heavy; keep it only for recent sessions.
    for s in kept[:-15]:
        s.pop("high_names", None)
        s.pop("low_names", None)

    current = sessions[-1]
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "universe": args.symbols or args.universe,
            "symbols_used": len(bars),
            "sessions_total": len(sessions),
            "params": {**DEFAULTS, **params},
            "source": "Yahoo Finance via yfinance (traded quantity, not delivery)",
        },
        "bands": [{"lo": lo, "hi": (None if hi > 1e8 else hi), "name": n, "action": a}
                  for lo, hi, n, a in BANDS],
        "distribution": dist,
        "sessions": kept,
        "current": current,
        "percentile": percentile_of(sessions, current["ratio"]),
    }

    with open(args.out, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  wrote {args.out}")

    if args.csv_out:
        with open(args.csv_out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "symbol", "open", "high", "low", "close", "volume"])
            for sym, blist in bars.items():
                for b in blist:
                    w.writerow([b["date"], sym, b["open"], b["high"],
                                b["low"], b["close"], int(b["volume"])])
        print(f"  wrote {args.csv_out}")

    print("\n" + "=" * 58)
    print(f"  {current['date']}   RATIO {current['ratio']:.2f}   {current['regime']}")
    print(f"  {current['n_high']} high-vol / {current['n_low']} low-vol "
          f"of {current['n_counted']} stocks")
    print(f"  slope(3d) {current['slope_label']}   "
          f"day {current['days_in_regime']} in regime")
    print(f"  breadth {current['adv']} up / {current['dec']} dn   "
          f"closes {current['upper_half']} upper / {current['lower_half']} lower")
    print(f"  {current['verdict']}")
    print("=" * 58)
    print("\nOpen the dashboard:  python -m http.server 8000   ->  "
          "http://localhost:8000/regime.html")


if __name__ == "__main__":
    main()
