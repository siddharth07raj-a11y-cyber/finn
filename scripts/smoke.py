"""Live smoke test: hits every upstream once and says plainly what works from THIS machine.

    python scripts/smoke.py [TICKER]

Run it locally and again on your host: exchanges treat datacentre IPs differently.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FINN_DATA_MODE"] = "live"
from finn import config, llm  # noqa: E402
import importlib  # noqa: E402

# finn.sources also exports functions named prices() / announcements(), so load the modules by path
ann, documents, prices, screener = (importlib.import_module(f"finn.sources.{m}") for m in ("announcements", "documents", "prices", "screener"))

SYM = (sys.argv[1] if len(sys.argv) > 1 else "RELIANCE").upper()
ok_all = True


def check(name, fn):
    global ok_all
    try:
        print(f"PASS  {name}: {fn()}")
        return True
    except Exception as e:  # noqa: BLE001
        ok_all = False
        print(f"FAIL  {name}: {type(e).__name__}: {str(e)[:160]}")
        return False


co = {}
end = datetime.now(config.IST).date()
start = end - timedelta(days=14)
check("Yahoo prices", lambda: (lambda p: f"{len(p['rows'])} sessions, last close {p['rows'][-1]['c']} on {p['rows'][-1]['d']}")(prices.history(SYM)))
if check("screener.in fundamentals", lambda: (co.update(screener.company(SYM)), f"{co['name']}, latest quarter {co['quarters']['cols'][-1]}, "
         f"{len(co['docs']['concalls'])} concalls, {len(co['docs']['annual_reports'])} annual reports, BSE {co['bse_code']}")[1]):
    t = next((c["transcript"] for c in co["docs"]["concalls"] if c["transcript"]), None)
    if t:
        check("Transcript PDF text", lambda: (lambda pg: f"{len(pg)} pages, {sum(map(len, pg))} characters")(documents.pages(t)))
    check("screener.in filings list", lambda: f"{len(ann.from_screener(SYM, start, end, company=co))} recent items")
check("NSE filings API", lambda: f"{len(ann.from_nse(SYM, start, end))} filings in 14 days")
check("BSE filings API", lambda: f"{len(ann.from_bse(SYM, start, end, bse_code=co.get('bse_code')))} filings in 14 days")
if llm.ready():
    for tier in ("cheap", "strong"):
        if not check(f"Model ({tier}: {llm._model(tier)})", lambda: (llm.chat(tier, "Reply with the single word OK.", "ping", json_mode=False, max_tokens=5)
                     or (_ for _ in ()).throw(RuntimeError(llm.LEDGER["last_error"] or "no reply")))):
            try:
                import requests
                r = requests.get(config.LLM_BASE.rstrip("/") + "/models", headers={"Authorization": f"Bearer {config.LLM_KEY}"}, timeout=20)
                print("      models your key can use:", ", ".join(m["id"] for m in r.json().get("data", [])[:40]))
            except Exception:  # noqa: BLE001
                pass
else:
    print("SKIP  Model: no FINN_LLM_KEY / FINN_MODEL_CHEAP set (FINN runs on rules and arithmetic)")
print("\nFilings need only ONE of NSE / BSE / screener to pass." if not ok_all else "\nAll sources answered.")
