"""
Daily run for one market: screen it, compare with the previous run, write the
report and send a short summary on Telegram.

Used by the Home Assistant add-on (ha-addon/), but runs anywhere:

    set TELEGRAM_TOKEN=123:ABC
    set TELEGRAM_CHAT_ID=987654
    python daily.py cac60          # or sp500
"""

import html
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from cac40_screener import CAC60, build, write_report
from sp500_screener import sp500_constituents

HERE = Path(__file__).resolve().parent

MARKETS = {
    "cac60": {"title": "CAC 60", "currency": "€", "universe": lambda: CAC60},
    "sp500": {"title": "S&P 500", "currency": "$", "universe": sp500_constituents},
}
SIGNALS = ["Strong buy", "Buy", "Hold", "Avoid"]
RANK = {s: i for i, s in enumerate(reversed(SIGNALS))}  # Avoid 0 .. Strong buy 3


def load_previous(path: Path) -> dict:
    """{ticker: row} from the previous run, empty on the first run."""
    try:
        return {r["ticker"]: r for r in json.loads(path.read_text(encoding="utf-8"))["stocks"]}
    except (OSError, ValueError, KeyError):
        return {}


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #

def summarize(title: str, rows: list, previous: dict, link: str = None, cap: int = 8) -> str:
    """Short Telegram message (HTML) focused on what changed since the last run."""
    esc = html.escape

    def label(r, extra=""):
        return f"{esc(r['name'][:24])}{extra}"

    def listing(items):
        return ", ".join(items[:cap]) + (f" … +{len(items) - cap}" if len(items) > cap else "")

    def prev(r):
        return previous.get(r["ticker"])

    counts = Counter(r["signal"] for r in rows)
    lines = [f"📈 <b>{esc(title)}</b> · {datetime.now():%d/%m %H:%M}",
             " · ".join(f"{s} {counts.get(s, 0)}" for s in SIGNALS), ""]

    if previous:
        new_sb = [r for r in rows if r["signal"] == "Strong buy" and prev(r) and prev(r)["signal"] != "Strong buy"]
        ups = [r for r in rows if prev(r) and r not in new_sb and RANK[r["signal"]] > RANK[prev(r)["signal"]]]
        downs = [r for r in rows if prev(r) and RANK[r["signal"]] < RANK[prev(r)["signal"]]]
        if new_sb:
            lines.append("🟢 New Strong buy: " + listing([label(r, f" ({r['score']:.0f})") for r in new_sb]))
        if ups:
            lines.append("⬆️ Upgraded: " + listing([label(r, f" → {r['signal']}") for r in ups]))
        if downs:
            lines.append("🔻 Downgraded: " + listing([label(r, f" → {r['signal']}") for r in downs]))
        if not (new_sb or ups or downs):
            lines.append("No signal change since the last run.")
    else:
        lines.append("First run: changes will be listed from the next one.")

    oversold = sorted((r for r in rows if r["rsi"] is not None and r["rsi"] < 30), key=lambda r: r["rsi"])
    if oversold:
        new = lambda r: " 🆕" if prev(r) and (prev(r).get("rsi") or 100) >= 30 else ""
        lines.append("⚠️ RSI &lt; 30: " + listing([label(r, f" ({r['rsi']:.0f}){new(r)}") for r in oversold]))
    if previous:
        overbought = [r for r in rows if (r["rsi"] or 0) > 70 and prev(r) and (prev(r).get("rsi") or 0) <= 70]
        if overbought:
            lines.append("🔥 Now overbought (RSI &gt; 70): " + listing([label(r, f" ({r['rsi']:.0f})") for r in overbought]))

    crossed = [r for r in rows if (r.get("macd_hist") or 0) > 0 and (r.get("macd_hist_prev") or 0) <= 0]
    if crossed:
        lines.append("✨ MACD bullish crossover: " + listing([label(r) for r in crossed]))

    lines.append("🏆 Top 5: " + " · ".join(label(r, f" {r['score']:.0f}") for r in rows[:5]))

    partial = sum(1 for r in rows if r.get("partial"))
    if partial:
        lines.append(f"<i>{partial} stocks scored without fundamentals (Yahoo rate limit).</i>")
    if link:
        lines += ["", f'👉 <a href="{esc(link)}">Full report</a>']
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #

def send_telegram(token: str, chat_id: str, text: str, attachment: Path = None):
    api = f"https://api.telegram.org/bot{token}"
    r = requests.post(f"{api}/sendMessage", timeout=30, json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    r.raise_for_status()
    if attachment:
        with attachment.open("rb") as f:
            r = requests.post(f"{api}/sendDocument", timeout=120, data={"chat_id": chat_id},
                              files={"document": (attachment.name, f, "text/html")})
        r.raise_for_status()


def update_ha_sensor(market: str, title: str, rows: list, link: str = None):
    """sensor.boursicateur_<market> through the Supervisor API (only inside the add-on).
    State = number of Strong buys; the details are in the attributes."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    counts = Counter(r["signal"] for r in rows)
    attrs = {
        "friendly_name": f"Boursicateur {title}",
        "icon": "mdi:finance",
        "unit_of_measurement": "stocks",
        **{s.lower().replace(" ", "_"): counts.get(s, 0) for s in SIGNALS},
        "top": [{"ticker": r["ticker"], "name": r["name"], "score": r["score"], "signal": r["signal"]}
                for r in rows[:5]],
        "oversold": [r["name"] for r in rows if r["rsi"] is not None and r["rsi"] < 30],
        "report_url": link,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    r = requests.post(f"http://supervisor/core/api/states/sensor.boursicateur_{market}", timeout=30,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"state": counts.get("Strong buy", 0), "attributes": attrs})
    r.raise_for_status()


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def run(market: str, telegram_token: str = None, telegram_chat_id: str = None, attach_report: bool = True,
        out_dir: Path = HERE, data_dir: Path = HERE, report_base_url: str = None):
    m = MARKETS[market]
    out_dir, data_dir = Path(out_dir), Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_html, out_json = out_dir / f"{market}_report.html", data_dir / f"{market}_data.json"
    link = f"{report_base_url.rstrip('/')}/{out_html.name}" if report_base_url else None

    previous = load_previous(out_json)
    rows = build(m["universe"](), verbose=False)
    write_report(rows, f"{m['title']} Screener", out_html, out_json, m["currency"])
    text = summarize(m["title"], rows, previous, link)
    print("\n" + text + "\n")

    if telegram_token and telegram_chat_id:
        try:
            send_telegram(telegram_token, telegram_chat_id, text, out_html if attach_report else None)
            print("Telegram summary sent.")
        except requests.RequestException as e:
            print(f"  ! Telegram failed: {e}", file=sys.stderr)
    else:
        print("Telegram not configured: summary not sent.")

    try:
        update_ha_sensor(market, m["title"], rows, link)
    except requests.RequestException as e:
        print(f"  ! Home Assistant sensor update failed: {e}", file=sys.stderr)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2 or sys.argv[1] not in MARKETS:
        sys.exit(f"Usage: python daily.py {{{'|'.join(MARKETS)}}}")
    run(sys.argv[1], os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))


if __name__ == "__main__":
    main()
