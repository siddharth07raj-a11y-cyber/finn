"""End-of-day price & volume from Yahoo Finance's chart endpoint (what yfinance wraps)."""
from datetime import datetime, timezone, timedelta

from .. import http

HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def parse_chart(payload, symbol):
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        err = (payload.get("chart") or {}).get("error") or {}
        raise ValueError(f"Yahoo: no data for {symbol}: {err.get('description', 'empty result')}")
    r = res[0]
    meta = r.get("meta", {})
    off = timedelta(seconds=meta.get("gmtoffset", 19800))
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for i, ts in enumerate(r.get("timestamp") or []):
        c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
        if c is None:
            continue  # holiday / halted session
        d = (datetime.fromtimestamp(ts, timezone.utc) + off).strftime("%Y-%m-%d")
        g = lambda k: (q.get(k) or [None] * (i + 1))[i]  # noqa: E731
        rows.append({"d": d, "o": g("open"), "h": g("high"), "l": g("low"),
                     "c": round(c, 2), "v": int(g("volume") or 0)})
    if not rows:
        raise ValueError(f"Yahoo: empty series for {symbol}")
    return {"symbol": symbol, "name": meta.get("longName") or meta.get("shortName") or symbol,
            "currency": meta.get("currency", "INR"), "rows": rows, "source": "Yahoo Finance"}


def history(symbol, rng="1y"):
    last = None
    for suffix in (".NS", ".BO"):
        for host in HOSTS:
            try:
                r = http.get(f"https://{host}/v8/finance/chart/{symbol}{suffix}",
                             params={"range": rng, "interval": "1d", "events": "div,splits"},
                             timeout=15)
                return parse_chart(r.json(), symbol)
            except Exception as e:  # noqa: BLE001
                last = e
    try:  # optional: use yfinance when it is installed
        import yfinance as yf  # type: ignore
        df = yf.Ticker(symbol + ".NS").history(period=rng, interval="1d", auto_adjust=False)
        rows = [{"d": i.strftime("%Y-%m-%d"), "o": float(r.Open), "h": float(r.High), "l": float(r.Low),
                 "c": round(float(r.Close), 2), "v": int(r.Volume)} for i, r in df.iterrows()]
        if rows:
            return {"symbol": symbol, "name": symbol, "currency": "INR", "rows": rows, "source": "yfinance"}
    except Exception:  # noqa: BLE001
        pass
    raise last or RuntimeError(f"no price data for {symbol}")
