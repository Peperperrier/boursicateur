# Boursicateur

Stock screeners for the **CAC 60** (CAC 40 + CAC Next 20) and the **S&P 500**. They download prices and
fundamentals from Yahoo Finance, compute technical and valuation indicators, give
each stock a score and a signal (**Strong buy / Buy / Hold / Avoid**), and write a
self-contained HTML report you open in your browser.

> This is a mechanical screen, not financial advice. Use it to find stocks worth
> researching, not as a buy/sell decision.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

## Usage

| Command | What it does |
|---|---|
| `run.bat` | CAC 60 report, opened in the browser (Windows, double-click) |
| `run_sp500.bat` | S&P 500 report, opened in the browser (Windows, double-click) |
| `python cac40_screener.py --open` | Same as `run.bat` |
| `python sp500_screener.py --open` | Same as `run_sp500.bat` |
| `python sp500_screener.py --top 100` | Only the 100 largest S&P 500 companies |
| `--refresh` (either script) | Ignore the 24h cache and fetch all fundamentals again |

Outputs are written next to the scripts:

- `cac60_report.html` / `sp500_report.html`: the report (open it in any browser)
- `cac60_data.json` / `sp500_data.json`: the raw data behind it

A run takes about 30 seconds for the CAC 60 and 1 minute for the S&P 500, longer
if Yahoo is rate-limiting you (see below).

## The report

- Click a column header to sort, a row to see the details and why it got its score.
- Filter by name, sector, RSI (oversold / overbought), P/E or uptrend.
- Click a signal card (Strong buy, Buy…) at the top to show only those stocks.
- Follows your system's light / dark theme.

## Indicators

| Indicator | How to read it |
|---|---|
| **RSI (14)** | Momentum from 0 to 100. Below 30 the stock is *oversold* (possible rebound), above 70 *overbought* (possible pullback). The arrow shows the change over the last week. |
| **P/E (PER)** | Price / last 12 months' earnings. Lower is cheaper, but compare within a sector (banks ~6–10, luxury ~20–30). |
| **Forward P/E** | Price / expected earnings. Lower than P/E means earnings are expected to grow. |
| **PEG** | P/E divided by earnings growth. Below 1 is often considered attractive. |
| **SMA 50 / SMA 200** | 50 and 200-day moving averages. Price above SMA 200 = long-term uptrend; SMA 50 above SMA 200 = "golden cross". |
| **MACD** | Trend momentum. The histogram turning positive is a bullish signal. |
| **Bollinger %B** | Position in the Bollinger bands: below 0 = under the lower band, above 1 = over the upper band. |
| **From 52w high / low** | Distance from the 1-year high and low. |
| **Performance** | Price change over 1, 3, 6 and 12 months; yearly volatility. |
| **Dividend yield, payout** | Income and whether the dividend is covered by earnings. |
| **ROE, profit margin, debt/equity** | Quality: ROE above 15% is good, debt/equity above 200% is high. |
| **Upside, Reco** | Distance to the analysts' average price target; consensus from 1 (strong buy) to 5 (sell). |

## Scoring

Each stock gets points from simple rules (e.g. RSI below 30: +2, P/E above 30: −2),
grouped into four pillars. Each pillar is scaled to 0–100, then combined:

| Pillar | Weight | Based on |
|---|---|---|
| Value | 35% | P/E, forward P/E, PEG, dividend yield |
| Momentum | 25% | RSI, SMA 50 / 200, MACD, distance from the 52w high |
| Quality | 20% | ROE, profit margin, debt/equity, payout ratio |
| Analysts | 20% | Price target upside, consensus |

| Score | Signal |
|---|---|
| 70 or more | Strong buy |
| 60 to 70 | Buy |
| 45 to 60 | Hold |
| under 45 | Avoid |

The rules and thresholds live in `score()` in `cac40_screener.py`; both screeners use
them. They are the same for every sector and market, so US tech stocks rarely look
"cheap" on P/E: compare stocks within a sector.

## Yahoo Finance rate limits

Yahoo limits how many requests it accepts. When it does, you'll see messages like
`Too Many Requests` or `Crumb fetch rate-limited (HTTP 429)`. The screeners handle it:

- blocked requests are retried after 5s, 10s, then 20s;
- fundamentals are cached for 24 hours in `.cache/fundamentals.json`, so a rerun
  only fetches what's missing;
- stocks without fundamentals are scored on technicals only and marked
  "⚠ no fundamentals" in the report;
- if Yahoo returns nothing at all, the previous report is kept.

If many stocks are missing, wait a few minutes and run the script again.

## Daily summary on Telegram

`daily.py` runs one market, compares it with the previous run and sends a short
Telegram message: new Strong buys, upgrades / downgrades, RSI below 30, stocks
becoming overbought, MACD crossovers and the top 5, with the report attached.

```bash
set TELEGRAM_TOKEN=123456789:AAH...
set TELEGRAM_CHAT_ID=987654321
python daily.py cac60
```

### Home Assistant add-on

This repository is also a Home Assistant add-on repository, to run the daily
summary on a Home Assistant OS machine (e.g. a Raspberry Pi 4):
add `https://github.com/Peperperrier/boursicateur` in **Settings → Add-ons →
Add-on store → ⋮ → Repositories** and install **Boursicateur**. Home Assistant
automations trigger each market (CAC 60 at 18:00, S&P 500 at 22:30); the add-on
sends the Telegram summary, publishes the report under `/local/` and creates a
`sensor.boursicateur_<market>` sensor. Setup steps and automations:
[ha-addon/DOCS.md](ha-addon/DOCS.md).

## Customising

- **CAC 60 list**: the indices change a few times a year. Edit the `CAC40` and
  `CAC_NEXT20` dictionaries at the top of `cac40_screener.py` (Yahoo ticker → name).
  You can add any stock outside the indices the same way, e.g. `"BOL.PA": "Bolloré"`.
- **S&P 500 list**: fetched from Wikipedia at every run, nothing to maintain.
- **Another market**: copy `sp500_screener.py`, give it a `{ticker: name}` dictionary
  and call `build()` then `write_report()`.

## Files

| File | Role |
|---|---|
| `cac40_screener.py` | Indicators, scoring, data fetching, report writer, CAC 40 / CAC Next 20 lists |
| `sp500_screener.py` | S&P 500 list (from Wikipedia), reuses `cac40_screener.py` |
| `template.html` | Report page shared by both screeners |
| `daily.py` | Daily run: report, change summary, Telegram, Home Assistant sensor |
| `repository.yaml`, `ha-addon/` | Home Assistant add-on (config, Dockerfile, runner, docs) |
| `run.bat`, `run_sp500.bat` | Windows launchers |
| `requirements.txt` | Python dependencies (`yfinance`, `pandas`, `requests`, `lxml`) |
