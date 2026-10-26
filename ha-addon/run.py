"""
Home Assistant add-on entry point. Waits for commands on stdin, sent by the
hassio.addon_stdin action (input: cac60 or sp500), and runs that market.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import daily  # noqa: E402

OPTIONS = Path("/data/options.json")
# Older automations still send cac40: it now runs the CAC 60.
ALIASES = {"cac40": "cac60"}


def settings() -> dict:
    """Add-on options, re-read before each run so changes apply without a restart."""
    o = json.loads(OPTIONS.read_text(encoding="utf-8"))
    folder = o["www_folder"]
    return {
        "telegram_token": o.get("telegram_token"),
        "telegram_chat_id": o.get("telegram_chat_id"),
        "attach_report": o.get("attach_report", True),
        "out_dir": Path("/homeassistant/www") / folder,
        "data_dir": Path("/data"),
        "report_base_url": f"{o['ha_url'].rstrip('/')}/local/{folder}" if o.get("ha_url") else None,
    }


def main():
    print(f"Boursicateur ready. Send {' or '.join(daily.MARKETS)} with the hassio.addon_stdin action.")
    while True:
        chunk = os.read(0, 4096)
        if not chunk:
            sys.exit("stdin closed, stopping.")
        # The input arrives JSON-encoded ("cac60"), possibly several at once: keep the words.
        for cmd in re.findall(r"[a-z0-9]+", chunk.decode(errors="ignore").lower()):
            cmd = ALIASES.get(cmd, cmd)
            if cmd not in daily.MARKETS:
                print(f"Unknown command '{cmd}', expected one of: {', '.join(daily.MARKETS)}")
                continue
            print(f"=== {cmd} run started ===")
            try:
                daily.run(cmd, **settings())
            except (Exception, SystemExit) as e:  # never let one failed run stop the add-on
                print(f"  ! {cmd} run failed: {e!r}", file=sys.stderr)
            print(f"=== {cmd} run finished ===")


if __name__ == "__main__":
    main()
