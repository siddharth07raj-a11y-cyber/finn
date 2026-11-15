"""Scheduled push: run the brief for the default portfolio and send anything new to Telegram.

    python scripts/scan.py            # cron / GitHub Actions (see .github/workflows/scan.yml)

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Without them it prints what it would send.
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finn import cache, config, digest, sources  # noqa: E402

start, end, label = digest.window("24h")
d = digest.build(sources.portfolio(), start, end, label, config.DEFAULT_RULES)
sent, _ = cache.get("scan:sent")
sent = set(sent or [])
lines = []
for i in d["act"]:
    if i["id"] not in sent:
        lines.append(f"• {i['symbol']} [{i['category_label']}] {i['title']}" + (f" ({i['why'][0]})" if i["why"] else ""))
        sent.add(i["id"])
for m in d["moves"]:
    key = f"{m['symbol']}:{m['d']}"
    if key not in sent:
        why = f"likely: {m['why']['category_label']}" if m["why"] else "no filing explains it"
        lines.append(f"• {m['symbol']} {m['pct']:+.1f}%" + (f" on {m['volx']:.1f}× volume" if m["volx"] and m["volx"] >= 1.5 else "") + f" ({why})")
        sent.add(key)
cache.put("scan:sent", sorted(sent)[-500:])
if not lines:
    print("Nothing new.")
    sys.exit(0)
text = f"FINN: {len(lines)} new\n" + "\n".join(lines[:20])
print(text)
if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT:
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": config.TELEGRAM_CHAT, "text": text}, timeout=20)
    print("telegram:", r.status_code)
