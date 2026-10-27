# Changelog

## 1.1.1

- Fix: the Telegram summary is no longer lost when the connection drops
  (`Connection reset by peer`, timeouts, Telegram server errors). It is now retried
  up to 4 times, waiting 10s, 20s and 30s between attempts.

## 1.1.0

- Screen the CAC 60 (CAC 40 + CAC Next 20) instead of the CAC 40.

## 1.0.0

- First release: daily Telegram summary, HTML report and Home Assistant sensor per market.
