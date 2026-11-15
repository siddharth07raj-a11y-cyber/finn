"""Unusual end-of-day moves, on thresholds the investor sets."""


def scan(px, rules, sessions=30):
    """Return (triggered sessions, latest-session stats) for one symbol's price history."""
    rows, lb = px["rows"], max(3, int(rules.get("lookback", 20)))
    hits, last = [], None
    for i in range(max(1, len(rows) - sessions), len(rows)):
        r, prev = rows[i], rows[i - 1]
        if not prev["c"]:
            continue
        pct = 100 * (r["c"] / prev["c"] - 1)
        base = [x["v"] for x in rows[max(0, i - lb):i] if x["v"]]
        volx = r["v"] / (sum(base) / len(base)) if base and r["v"] else None
        kinds = []
        if abs(pct) >= float(rules.get("px", 4)):
            kinds.append("price")
        if volx is not None and volx >= float(rules.get("vol", 2)):
            kinds.append("volume")
        rec = {"symbol": px["symbol"], "d": r["d"], "pct": round(pct, 2),
               "volx": round(volx, 2) if volx is not None else None, "close": r["c"], "kinds": kinds}
        if kinds:
            hits.append(rec)
        last = rec
    if last:
        last = dict(last, spark=[x["c"] for x in rows[-30:]])
    return hits, last
