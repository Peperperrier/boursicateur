# Boursicateur add-on

Runs the CAC 40 / S&P 500 screener on Home Assistant, sends a short summary on
Telegram, publishes the HTML report in Home Assistant and creates a sensor per market.

The add-on waits for commands: your Home Assistant automations decide when each
market runs (by default CAC 40 at 18:00 and S&P 500 at 22:30, after each market closes).

## 1. Create the Telegram bot

1. In Telegram, talk to **@BotFather**, send `/newbot` and follow the steps.
   Keep the **token** it gives you (looks like `123456789:AAH...`).
2. Send any message to your new bot (otherwise it can't write to you).
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and find
   `"chat":{"id":123456789` : that number is your **chat ID**.

## 2. Install the add-on

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**, add
   `https://github.com/Peperperrier/boursicateur`.
2. Refresh the page, open **Boursicateur**, click **Install** (the first build takes
   5–10 minutes on a Raspberry Pi 4).
3. In the **Configuration** tab, fill in:

| Option | Description |
|---|---|
| `telegram_token` | Bot token from @BotFather |
| `telegram_chat_id` | Your chat ID |
| `attach_report` | Also send the HTML report as a file in Telegram (open it on your phone) |
| `www_folder` | Folder under `/config/www/` for the reports. Files there are reachable **without login** at `/local/<folder>/`: use a hard-to-guess name if your HA is reachable from the internet |
| `ha_url` | Optional. Your HA address (e.g. `https://xxxx.ui.nabu.casa`) to put a link to the report in the message |

4. **Start** the add-on. The log shows `Boursicateur ready.`

## 3. Schedule the runs

Create these automations (**Settings → Automations → ⋮ → Edit in YAML**).
The add-on ID below is the one Home Assistant gives when the repository is added
with the exact URL above; check it in your browser's address bar on the add-on page
and adjust if it differs.

```yaml
alias: Boursicateur - CAC 40
description: CAC 40 screener after the Paris close
triggers:
  - trigger: time
    at: "18:00:00"
conditions:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
actions:
  - action: hassio.addon_stdin
    data:
      addon: e4274ed5_boursicateur
      input: cac40
mode: single
```

```yaml
alias: Boursicateur - S&P 500
description: S&P 500 screener after the New York close
triggers:
  - trigger: time
    at: "22:30:00"
conditions:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
actions:
  - action: hassio.addon_stdin
    data:
      addon: e4274ed5_boursicateur
      input: sp500
mode: single
```

To stop a market, disable its automation. To run one right now, use
**Developer tools → Actions → `hassio.addon_stdin`** with the same data, and follow the
progress in the add-on **Log** tab.

## What you get

- **Telegram message**: signal counts, new Strong buys, upgrades / downgrades since the
  last run, RSI below 30, stocks becoming overbought, MACD crossovers, top 5.
- **Report**: `/config/www/<www_folder>/cac40_report.html` (and `sp500_report.html`),
  opens at `http://<your-ha>:8123/local/<www_folder>/cac40_report.html`. You can show it
  on a dashboard with a **Webpage** card.
  If `/config/www` didn't exist before the first run, restart Home Assistant once so
  that `/local/` serves it.
- **Sensors** `sensor.boursicateur_cac40` and `sensor.boursicateur_sp500`: the state is
  the number of Strong buys; the attributes hold the other counts, the top 5, the
  oversold stocks and the report URL. They are recreated at each run (they disappear
  after a Home Assistant restart until the next run).

Example: notify when a stock becomes oversold.

```yaml
alias: Boursicateur - oversold alert
triggers:
  - trigger: state
    entity_id: sensor.boursicateur_cac40
    attribute: oversold
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.oversold | length > 0 }}"
actions:
  - action: persistent_notification.create
    data:
      title: CAC 40 oversold
      message: "{{ trigger.to_state.attributes.oversold | join(', ') }}"
```

## Updating

The add-on downloads the screener code from GitHub when it is built. After a change
on GitHub, open the add-on and click **⋮ → Rebuild**.
