"""
CAC 60 screener (CAC 40 + CAC Next 20): fetches prices and fundamentals from
Yahoo Finance, computes technical / valuation indicators and a composite score,
then writes a self-contained HTML report (cac60_report.html) plus the raw data
(cac60_data.json).

Usage:
    python cac40_screener.py            # generate report
    python cac40_screener.py --open     # generate and open in the browser

Not financial advice: the score is a mechanical screen, use it as a starting
point for your own research.
"""

import argparse
import json
import math
import os
import random
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUT_HTML = HERE / "cac60_report.html"
OUT_JSON = HERE / "cac60_data.json"
# The Home Assistant add-on keeps its cache in its persistent /data folder.
CACHE = Path(os.environ.get("BOURSICATEUR_CACHE") or HERE / ".cache" / "fundamentals.json")
CACHE_HOURS = 24  # fundamentals move slowly: reuse them to avoid Yahoo rate limits

# CAC 40 and CAC Next 20 constituents (Yahoo tickers). The index compositions change
# a few times a year: edit these lists if needed. Unknown / delisted tickers are skipped.
CAC40 = {
    "AC.PA": "Accor",
    "AI.PA": "Air Liquide",
    "AIR.PA": "Airbus",
    "MT.AS": "ArcelorMittal",
    "CS.PA": "AXA",
    "BNP.PA": "BNP Paribas",
    "EN.PA": "Bouygues",
    "BVI.PA": "Bureau Veritas",
    "CAP.PA": "Capgemini",
    "CA.PA": "Carrefour",
    "ACA.PA": "Crédit Agricole",
    "BN.PA": "Danone",
    "DSY.PA": "Dassault Systèmes",
    "FGR.PA": "Eiffage",
    "ENGI.PA": "Engie",
    "EL.PA": "EssilorLuxottica",
    "ERF.PA": "Eurofins Scientific",
    "ENX.PA": "Euronext",
    "RMS.PA": "Hermès",
    "KER.PA": "Kering",
    "OR.PA": "L'Oréal",
    "LR.PA": "Legrand",
    "MC.PA": "LVMH",
    "ML.PA": "Michelin",
    "ORA.PA": "Orange",
    "RI.PA": "Pernod Ricard",
    "PUB.PA": "Publicis",
    "RNO.PA": "Renault",
    "SAF.PA": "Safran",
    "SGO.PA": "Saint-Gobain",
    "SAN.PA": "Sanofi",
    "SU.PA": "Schneider Electric",
    "GLE.PA": "Société Générale",
    "STLAP.PA": "Stellantis",
    "STMPA.PA": "STMicroelectronics",
    "HO.PA": "Thales",
    "TTE.PA": "TotalEnergies",
    "URW.PA": "Unibail-Rodamco-Westfield",
    "VIE.PA": "Veolia",
    "DG.PA": "Vinci",
}

CAC_NEXT20 = {
    "ABVX.PA": "Abivax",
    "ALO.PA": "Alstom",
    "AMUN.PA": "Amundi",
    "AKE.PA": "Arkema",
    "BIM.PA": "bioMérieux",
    "AM.PA": "Dassault Aviation",
    "EDEN.PA": "Edenred",
    "GTT.PA": "Gaztransport & Technigaz",
    "GET.PA": "Getlink",
    "IPN.PA": "Ipsen",
    "LI.PA": "Klépierre",
    "NEX.PA": "Nexans",
    "RXL.PA": "Rexel",
    "DIM.PA": "Sartorius Stedim Biotech",
    "SCR.PA": "SCOR",
    "SW.PA": "Sodexo",
    "SOI.PA": "Soitec",
    "SPIE.PA": "SPIE",
    "TE.PA": "Technip Energies",
    "TEP.PA": "Teleperformance",
}

CAC60 = {**CAC40, **CAC_NEXT20}


# --------------------------------------------------------------------------- #
# Technical indicators
# --------------------------------------------------------------------------- #

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger_pct_b(close: pd.Series, period=20, k=2.0) -> pd.Series:
    """%B: 0 = on lower band, 1 = on upper band."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return (close - (mid - k * std)) / (2 * k * std)


def pct_change(close: pd.Series, days: int):
    if len(close) <= days:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1)


def clean(v):
    """Turn NaN / inf / numpy types into JSON-friendly values."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) or math.isinf(f) else f


def technicals(close: pd.Series) -> dict:
    close = close.dropna()
    if len(close) < 30:
        return {}
    r = rsi(close)
    m_line, m_sig, m_hist = macd(close)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    last = float(close.iloc[-1])
    year = close.iloc[-252:]
    hi, lo = float(year.max()), float(year.min())
    daily_ret = close.pct_change().iloc[-252:]

    spark = close.iloc[-126:]  # ~6 months for the sparkline
    step = max(1, len(spark) // 60)
    return {
        "price": last,
        "rsi": clean(r.iloc[-1]),
        "rsi_prev": clean(r.iloc[-6]) if len(r) > 6 else None,  # one week ago
        "sma50": clean(sma50.iloc[-1]),
        "sma200": clean(sma200.iloc[-1]),
        "macd": clean(m_line.iloc[-1]),
        "macd_signal": clean(m_sig.iloc[-1]),
        "macd_hist": clean(m_hist.iloc[-1]),
        "macd_hist_prev": clean(m_hist.iloc[-2]),
        "bb_pct_b": clean(bollinger_pct_b(close).iloc[-1]),
        "high_52w": hi,
        "low_52w": lo,
        "from_high": last / hi - 1,
        "from_low": last / lo - 1,
        "perf_1m": pct_change(close, 21),
        "perf_3m": pct_change(close, 63),
        "perf_6m": pct_change(close, 126),
        "perf_1y": pct_change(close, 252),
        "volatility": clean(daily_ret.std() * math.sqrt(252)),
        "spark": [round(float(x), 2) for x in spark.iloc[::step]],
    }


# --------------------------------------------------------------------------- #
# Fundamentals
# --------------------------------------------------------------------------- #

def fetch_info(ticker: str, attempts: int = 4) -> dict:
    """Ticker.info with exponential backoff: Yahoo answers HTTP 429 (or an empty
    payload) when it rate-limits us."""
    for i in range(attempts):
        try:
            info = yf.Ticker(ticker).info or {}
            if len(info) > 5:
                return info
            err = "empty response"
        except Exception as e:
            err = e
        if i < attempts - 1:
            time.sleep(5 * 2 ** i + random.random() * 3)  # 5s, 10s, 20s (+ jitter)
    print(f"  ! {ticker}: fundamentals unavailable ({err})", file=sys.stderr)
    return {}


def fundamentals(ticker: str) -> dict:
    info = fetch_info(ticker)
    if not info:
        return {}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    div_rate = info.get("dividendRate")
    div_yield = div_rate / price if div_rate and price else info.get("trailingAnnualDividendYield")
    target = info.get("targetMeanPrice")

    return {
        "sector": info.get("sector"),
        "market_cap": clean(info.get("marketCap")),
        "pe": clean(info.get("trailingPE")),
        "forward_pe": clean(info.get("forwardPE")),
        "peg": clean(info.get("trailingPegRatio") or info.get("pegRatio")),
        "pb": clean(info.get("priceToBook")),
        "ev_ebitda": clean(info.get("enterpriseToEbitda")),
        "div_yield": clean(div_yield),
        "payout": clean(info.get("payoutRatio")),
        "roe": clean(info.get("returnOnEquity")),
        "margin": clean(info.get("profitMargins")),
        "debt_equity": clean(info.get("debtToEquity")),  # in %
        "rev_growth": clean(info.get("revenueGrowth")),
        "eps_growth": clean(info.get("earningsGrowth")),
        "beta": clean(info.get("beta")),
        "target": clean(target),
        "upside": clean(target / price - 1) if target and price else None,
        "reco_mean": clean(info.get("recommendationMean")),  # 1 = strong buy .. 5 = sell
        "reco_key": info.get("recommendationKey"),
        "analysts": info.get("numberOfAnalystOpinions"),
    }


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def score(d: dict) -> dict:
    """Each rule adds points to one of 4 pillars. Returns pillar scores, total
    (0-100), signal and the list of reasons shown in the report."""
    pillars = {"value": 0.0, "momentum": 0.0, "quality": 0.0, "sentiment": 0.0}
    reasons = []

    def add(pillar, pts, why):
        pillars[pillar] += pts
        reasons.append({"pts": pts, "why": why, "pillar": pillar})

    # --- Valuation ---------------------------------------------------------
    pe = d.get("pe")
    if d.get("market_cap") is None:
        add("value", 0, "Fundamentals unavailable from Yahoo: score based on technicals only, rerun later")
    elif pe is None or pe <= 0:
        if d.get("forward_pe") and d["forward_pe"] > 0:
            add("value", 0, "No trailing P/E (loss), forward P/E positive")
        else:
            add("value", -1, "Negative / unavailable earnings")
    elif pe < 10:
        add("value", 2, f"Low P/E ({pe:.1f})")
    elif pe < 15:
        add("value", 1, f"Reasonable P/E ({pe:.1f})")
    elif pe > 30:
        add("value", -2, f"Expensive P/E ({pe:.1f})")
    elif pe > 22:
        add("value", -1, f"High P/E ({pe:.1f})")

    fpe = d.get("forward_pe")
    if pe and fpe and pe > 0 and fpe > 0:
        if fpe < pe * 0.9:
            add("value", 1, f"Earnings expected to grow (fwd P/E {fpe:.1f} < {pe:.1f})")
        elif fpe > pe * 1.1:
            add("value", -1, f"Earnings expected to fall (fwd P/E {fpe:.1f} > {pe:.1f})")

    peg = d.get("peg")
    if peg is not None and peg > 0:
        if peg < 1:
            add("value", 1, f"PEG < 1 ({peg:.2f}): growth at a fair price")
        elif peg > 2.5:
            add("value", -1, f"High PEG ({peg:.2f})")

    dy = d.get("div_yield")
    if dy is not None and dy >= 0.04:
        add("value", 1, f"High dividend yield ({dy*100:.1f}%)")

    # --- Momentum / technicals ---------------------------------------------
    r = d.get("rsi")
    if r is not None:
        if r < 30:
            add("momentum", 2, f"RSI oversold ({r:.0f})")
        elif r < 40:
            add("momentum", 1, f"RSI low ({r:.0f})")
        elif r > 75:
            add("momentum", -2, f"RSI strongly overbought ({r:.0f})")
        elif r > 70:
            add("momentum", -1, f"RSI overbought ({r:.0f})")

    price, s50, s200 = d.get("price"), d.get("sma50"), d.get("sma200")
    if price and s200:
        if price > s200:
            add("momentum", 1, "Price above 200-day average (long-term uptrend)")
        else:
            add("momentum", -1, "Price below 200-day average (long-term downtrend)")
    if s50 and s200:
        if s50 > s200:
            add("momentum", 1, "SMA50 > SMA200 (golden cross regime)")
        else:
            add("momentum", -1, "SMA50 < SMA200 (death cross regime)")

    h, hp = d.get("macd_hist"), d.get("macd_hist_prev")
    if h is not None and hp is not None:
        if h > 0 and hp <= 0:
            add("momentum", 1.5, "MACD bullish crossover (today)")
        elif h > 0:
            add("momentum", 0.5, "MACD above signal")
        elif h < 0 and hp >= 0:
            add("momentum", -1.5, "MACD bearish crossover (today)")
        else:
            add("momentum", -0.5, "MACD below signal")

    fh = d.get("from_high")
    if fh is not None and fh < -0.30 and price and s200 and price > s200 * 0.9:
        add("momentum", 0.5, f"{fh*100:.0f}% below 52w high, possible recovery")

    # --- Quality ------------------------------------------------------------
    roe = d.get("roe")
    if roe is not None:
        if roe > 0.15:
            add("quality", 1, f"High ROE ({roe*100:.0f}%)")
        elif roe < 0.05:
            add("quality", -1, f"Weak ROE ({roe*100:.0f}%)")

    margin = d.get("margin")
    if margin is not None:
        if margin > 0.15:
            add("quality", 1, f"High profit margin ({margin*100:.0f}%)")
        elif margin < 0:
            add("quality", -1, "Negative profit margin")

    de = d.get("debt_equity")
    if de is not None and d.get("sector") != "Financial Services":  # banks' leverage isn't comparable
        if de > 200:
            add("quality", -1, f"High debt/equity ({de:.0f}%)")
        elif de < 50:
            add("quality", 0.5, f"Low debt/equity ({de:.0f}%)")

    payout = d.get("payout")
    if payout is not None and payout > 1:
        add("quality", -0.5, f"Dividend payout > 100% ({payout*100:.0f}%)")

    # --- Sentiment (analysts) ---------------------------------------------
    up = d.get("upside")
    if up is not None:
        if up > 0.25:
            add("sentiment", 2, f"Analyst target +{up*100:.0f}%")
        elif up > 0.10:
            add("sentiment", 1, f"Analyst target +{up*100:.0f}%")
        elif up < 0:
            add("sentiment", -1, f"Price above analyst target ({up*100:.0f}%)")

    rm = d.get("reco_mean")
    if rm is not None:
        if rm <= 2.0:
            add("sentiment", 1, f"Analysts: buy consensus ({rm:.1f}/5)")
        elif rm >= 3.0:
            add("sentiment", -1, f"Analysts: hold/sell consensus ({rm:.1f}/5)")

    # Min / max achievable per pillar, used to normalise to 0-100.
    bounds = {"value": (-4, 5), "momentum": (-5.5, 6), "quality": (-3.5, 2.5), "sentiment": (-2, 3)}
    weights = {"value": 0.35, "momentum": 0.25, "quality": 0.2, "sentiment": 0.2}
    norm = {k: (pillars[k] - lo) / (hi - lo) * 100 for k, (lo, hi) in bounds.items()}
    partial = d.get("market_cap") is None
    total = norm["momentum"] if partial else sum(norm[k] * w for k, w in weights.items())

    if total >= 70:
        signal = "Strong buy"
    elif total >= 60:
        signal = "Buy"
    elif total >= 45:
        signal = "Hold"
    else:
        signal = "Avoid"

    return {"score": round(total, 1), "pillars": {k: round(v) for k, v in norm.items()},
            "signal": signal, "reasons": reasons, "partial": partial}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def download_closes(tickers: list, attempts: int = 3) -> dict:
    """{ticker: close series}. Tickers missing from a (rate-limited) batch are retried."""
    closes, todo = {}, list(tickers)
    for i in range(attempts):
        prices = yf.download(todo, period="2y", interval="1d", auto_adjust=True,
                             progress=False, group_by="ticker", threads=True)
        for t in todo:
            try:
                s = prices[t]["Close"].dropna()
            except KeyError:
                continue
            if len(s):
                closes[t] = s
        todo = [t for t in todo if t not in closes]
        if not todo or i == attempts - 1:
            break
        print(f"  {len(todo)} tickers without prices, retrying in {15 * (i + 1)}s...")
        time.sleep(15 * (i + 1))
    return closes


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cached_fundamentals(tickers: list, refresh: bool = False) -> dict:
    """Fundamentals from the local cache when fresher than CACHE_HOURS, Yahoo otherwise."""
    cache, now = load_cache(), time.time()
    fresh = {t: cache[t]["data"] for t in tickers
             if not refresh and t in cache and now - cache[t]["t"] < CACHE_HOURS * 3600}
    todo = [t for t in tickers if t not in fresh]
    print(f"Fundamentals: {len(fresh)} from cache, {len(todo)} to fetch...")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = dict(zip(todo, pool.map(fundamentals, todo)))
    for t, data in fetched.items():
        if data:  # never cache a failure
            cache[t] = {"t": now, "data": data}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {**fresh, **fetched}


def build(universe: dict, verbose: bool = True, refresh: bool = False) -> list:
    """universe: {yahoo_ticker: display_name}. Returns scored rows, best first."""
    tickers = list(universe)
    print(f"Downloading 2 years of prices for {len(tickers)} stocks...")
    closes = download_closes(tickers)
    funds = cached_fundamentals([t for t in tickers if t in closes], refresh)

    rows = []
    for t in tickers:
        tech = technicals(closes.get(t, pd.Series(dtype=float)))
        if not tech:
            print(f"  ! {t}: no price data, skipped", file=sys.stderr)
            continue
        row = {"ticker": t, "name": universe[t], **tech, **funds.get(t, {})}
        row.update(score(row))
        rows.append(row)
        if verbose:
            print(f"  {t:10} {universe[t]:28} RSI {row['rsi'] or 0:5.1f}  "
                  f"P/E {row.get('pe') or float('nan'):6.1f}  score {row['score']:5.1f}  {row['signal']}")

    missing = [r["ticker"] for r in rows if r["partial"]]
    if missing:
        print(f"\n  ! {len(missing)} stocks without fundamentals (Yahoo rate limit?), scored on "
              f"technicals only: {' '.join(missing[:20])}{' ...' if len(missing) > 20 else ''}\n"
              f"    Rerun in a few minutes: cached stocks are skipped, only these will be fetched.",
              file=sys.stderr)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def write_report(rows: list, title: str, out_html: Path, out_json: Path, currency: str = "€",
                 open_browser: bool = False):
    if not rows:  # keep the previous report rather than replacing it with an empty one
        sys.exit("No data received from Yahoo Finance (rate-limited?). Previous report kept; retry later.")
    payload ={"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "currency": currency, "stocks": rows}
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    html = TEMPLATE.read_text(encoding="utf-8").replace("__TITLE__", title).replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    out_html.write_text(html, encoding="utf-8")
    print(f"\nReport written to {out_html}")
    if open_browser:
        webbrowser.open(out_html.as_uri())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="open the report in the browser")
    ap.add_argument("--refresh", action="store_true", help=f"ignore the {CACHE_HOURS}h fundamentals cache")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # accents in names on the Windows console

    write_report(build(CAC60, refresh=args.refresh), "CAC 60 Screener", OUT_HTML, OUT_JSON, "€", args.open)


if __name__ == "__main__":
    main()
