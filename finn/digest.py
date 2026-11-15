"""The brief: every filing in a window, ranked, with the routine ones buried."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import cache, classify, config, enrich, moves, sources

WINDOWS = {"24h": 24, "3d": 72, "7d": 168, "30d": 720}
TOP_ROLES = ("top",)


def window(preset="24h", frm=None, to=None):
    now = datetime.now(config.IST)
    if frm:
        start = datetime.fromisoformat(frm).replace(tzinfo=config.IST)
        end = (datetime.fromisoformat(to).replace(tzinfo=config.IST) + timedelta(days=1)) if to else now
        return start, min(end, now), f"{start:%d %b} to {min(end, now):%d %b}"
    hours = WINDOWS.get(preset, 24)
    label = {"24h": "Last 24 hours", "3d": "Last 3 days", "7d": "Last 7 days", "30d": "Last 30 days"}.get(preset, "Last 24 hours")
    return now - timedelta(hours=hours), now, label


def _fetch_all(symbols, days):
    def one(sym):
        out = {"symbol": sym, "ann": [], "px": None, "err": []}
        try:
            out["ann"], meta = sources.announcements(sym, days)
            out["ann_stale"] = meta.get("stale", False)
        except Exception as e:  # noqa: BLE001
            out["err"].append(("filings", str(e)[:140]))
        try:
            out["px"], meta = sources.prices(sym)
            out["px_stale"] = meta.get("stale", False)
        except Exception as e:  # noqa: BLE001
            out["err"].append(("prices", str(e)[:140]))
        return out

    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(one, symbols))


def build(symbols, start, end, label, rules):
    days = min(120, max(30, (datetime.now(config.IST) - start).days + 2))
    data = _fetch_all(symbols, days)
    care, mute = set(rules.get("care", [])), set(rules.get("mute", []))

    # 1. price / volume triggers
    hits, last_by = [], {}
    for d in data:
        if d["px"]:
            h, last = moves.scan(d["px"], rules)
            last_by[d["symbol"]] = last
            hits += h
    last_session = max((v["d"] for v in last_by.values() if v), default=None)
    lo = min(start.date().isoformat(), last_session) if last_session else start.date().isoformat()
    hits = [h for h in hits if lo <= h["d"] <= end.date().isoformat()]
    move_on = {(h["symbol"], h["d"]): h for h in hits}
    sessions = {d["symbol"]: [r["d"] for r in d["px"]["rows"][-90:]] for d in data if d["px"]}

    def session_for(sym, dt_iso):
        """The trading session that first prices in a filing: same day if filed before
        the 15:30 close, otherwise the next session."""
        day, after = dt_iso[:10], dt_iso[11:16] >= "15:30"
        for s in sessions.get(sym, []):
            if s > day or (s == day and not after):
                return s if (datetime.fromisoformat(s) - datetime.fromisoformat(day)).days <= 4 else None
        return None

    # 2. filings in the window -> classify -> score
    raw = [a for d in data for a in d["ann"] if start.isoformat() <= a["dt"] <= end.isoformat()]
    cls = classify.classify_many(raw)
    items = []
    for a in raw:
        c = cls[a["id"]]
        score, why = c["score"], []
        if c["category"] in care:
            score += 10
        sess = session_for(a["symbol"], a["dt"])
        mv = move_on.get((a["symbol"], sess))
        if mv and c["score"] >= 30:
            score += 8
            bits = [f"{mv['pct']:+.1f}%"] + ([f"{mv['volx']:.1f}× volume"] if mv["volx"] and "volume" in mv["kinds"] else [])
            why.append("Stock moved " + " on ".join(bits))
        if c["category"] in mute:
            score = min(score, 20)
        tier = "act" if score >= 70 else "know" if score >= 35 else "noise"
        cache.put("item:" + a["id"], {"item": a, "cls": c})
        items.append({**{k: a[k] for k in ("id", "symbol", "company", "dt", "url", "source")}, "title": a.get("headline") or a["title"],
                      "category": c["category"], "category_label": classify.LABEL[c["category"]],
                      "subtype": c["subtype"], "score": min(100, score), "tier": tier, "why": why,
                      "summary": enrich.one_liner(a), "enrich_kind": enrich.kind_for(c) if tier != "noise" else None,
                      "move": {"pct": mv["pct"], "volx": mv["volx"]} if mv else None, "session": sess, "related": []})

    # 3. cluster same-company, same-day, same-topic filings under the strongest one
    items.sort(key=lambda x: x["dt"], reverse=True)
    items.sort(key=lambda x: -x["score"])
    heads, out = {}, []
    for it in items:
        key = (it["symbol"], it["dt"][:10], it["category"])
        if key in heads and it["tier"] != "noise":
            heads[key]["related"].append({"title": it["title"], "url": it["url"], "dt": it["dt"]})
            continue
        heads.setdefault(key, it)
        out.append(it)
    act = [i for i in out if i["tier"] == "act"]
    know = [i for i in out if i["tier"] == "know"]
    noise = [i for i in out if i["tier"] == "noise"]
    buried = {}
    for i in noise:
        buried.setdefault(i["category"], []).append({k: i[k] for k in ("id", "symbol", "dt", "title", "url")})
    buried = [{"category": k, "label": classify.LABEL[k], "count": len(v), "items": sorted(v, key=lambda x: x["dt"], reverse=True)}
              for k, v in sorted(buried.items(), key=lambda kv: -len(kv[1]))]

    # 4. explain each move with the filing most likely behind it
    for h in hits:
        cands = [i for i in act + know if i["symbol"] == h["symbol"] and i.get("session") == h["d"]]
        h["why"] = {"id": cands[0]["id"], "title": cands[0]["title"], "category_label": cands[0]["category_label"]} if cands else None
        h["spark"] = (last_by.get(h["symbol"]) or {}).get("spark") if h["d"] == (last_by.get(h["symbol"]) or {}).get("d") else None
    hits.sort(key=lambda h: (h["d"], abs(h["pct"])), reverse=True)

    total = len(raw)
    quiet = len(noise) + sum(len(i["related"]) for i in out)
    errs = [{"symbol": d["symbol"], "what": w, "error": e} for d in data for w, e in d["err"]]
    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "label": label},
        "counts": {"act": len(act), "know": len(know), "buried": quiet, "total": total, "moves": len(hits),
                   "holdings": len(symbols)},
        "act": act, "know": know, "buried": buried, "moves": hits, "last_session": last_session,
        "health": {"errors": errs, "stale": sorted({d["symbol"] for d in data if d.get("ann_stale") or d.get("px_stale")}),
                   "filings_ok": sum(1 for d in data if not any(w == "filings" for w, _ in d["err"])),
                   "prices_ok": sum(1 for d in data if d["px"])},
        "sample": sources.SAMPLE, "generated": datetime.now(config.IST).isoformat(),
    }


def spoken(d):
    """A short script for the listen-to-your-brief button."""
    c = d["counts"]
    parts = [f"{d['window']['label']}. {c['act']} item{'s' if c['act'] != 1 else ''} need you, {c['buried'] + c['know']} don't."]
    for i in d["act"][:6]:
        parts.append(f"{i['company']}: {i['category_label']}. {i['summary'] or i['title']}" + (f" {i['why'][0]}." if i["why"] else ""))
    unexplained = [m for m in d["moves"] if not m["why"]][:3]
    for m in unexplained:
        parts.append(f"{m['symbol']} moved {m['pct']:+.1f} percent" + (f" on {m['volx']:.1f} times normal volume" if m["volx"] and m["volx"] >= 1.5 else "") + ", with no filing to explain it.")
    return " ".join(parts)
