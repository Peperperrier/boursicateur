"""
S&P 500 screener: same indicators, scoring and report as cac40_screener.py,
applied to the S&P 500 constituents (list fetched from Wikipedia at each run).

Usage:
    python sp500_screener.py              # all ~500 stocks
    python sp500_screener.py --top 100    # only the 100 largest market caps
    python sp500_screener.py --open       # open the report in the browser
"""

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
import requests

from cac40_screener import build, write_report

HERE = Path(__file__).resolve().parent
OUT_HTML = HERE / "sp500_report.html"
OUT_JSON = HERE / "sp500_data.json"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def sp500_constituents() -> dict:
    """{yahoo_ticker: company name}. Yahoo uses '-' where the index uses '.' (BRK.B -> BRK-B)."""
    html = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (sp500-screener)"}, timeout=30).text
    table = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
    return {sym.replace(".", "-"): name for sym, name in zip(table["Symbol"], table["Security"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="open the report in the browser")
    ap.add_argument("--top", type=int, metavar="N", help="keep only the N largest companies by market cap")
    ap.add_argument("--refresh", action="store_true", help="ignore the 24h fundamentals cache")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    universe = sp500_constituents()
    print(f"{len(universe)} S&P 500 constituents")
    rows = build(universe, verbose=False, refresh=args.refresh)

    title = "S&P 500 Screener"
    if args.top:
        rows = sorted(rows, key=lambda r: r.get("market_cap") or 0, reverse=True)[:args.top]
        rows.sort(key=lambda r: r["score"], reverse=True)
        title = f"S&P 500 Screener — top {args.top}"

    for r in rows[:15]:
        print(f"  {r['ticker']:6} {r['name'][:30]:30} RSI {r['rsi'] or 0:5.1f}  "
              f"P/E {r.get('pe') or float('nan'):6.1f}  score {r['score']:5.1f}  {r['signal']}")
    write_report(rows, title, OUT_HTML, OUT_JSON, "$", args.open)


if __name__ == "__main__":
    main()
