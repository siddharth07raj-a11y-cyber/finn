"""Deterministic financial analysis. No model touches a number in this file.

Input is the standardised statement set for one company; output is a set of small
"cards", each with a one-line verdict computed by rule, a few stats and a series.
"""
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def ym(label):
    """'Sep 2026' -> (2026, 9); None for 'TTM' and anything else."""
    p = (label or "").split()
    if len(p) == 2 and p[0] in MONTHS and p[1].isdigit():
        return int(p[1]), MONTHS[p[0]]
    return None


def pct(new, old):
    if new is None or old is None or old <= 0:
        return None
    return round(100 * (new / old - 1), 1)


def row(tbl, key):
    return (tbl or {}).get("rows", {}).get(key) or []


def _last(vals):
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] is not None:
            return i
    return None


def cagr(vals, years):
    if len(vals) <= years or vals[-1] is None or vals[-1 - years] is None or vals[-1 - years] <= 0 or vals[-1] <= 0:
        return None
    return round(100 * ((vals[-1] / vals[-1 - years]) ** (1 / years) - 1), 1)


def headline(co):
    """Latest quarter: Revenue, EBITDA, PBT, PAT with QoQ and YoY."""
    q = co["quarters"]
    i = _last(row(q, "sales"))
    if i is None:
        return None
    fin = co.get("is_financial")
    # Lenders: "financing profit" excludes other income and misleads, so it is not shown.
    spec = [("sales", "Revenue")] + ([] if fin else [("operating_profit", "EBITDA")]) + [("pbt", "PBT"), ("net_profit", "PAT")]
    rows = []
    for key, label in spec:
        v = row(q, key)
        if not v:
            continue
        rows.append({"key": key, "label": label, "value": v[i],
                     "qoq": pct(v[i], v[i - 1]) if i >= 1 else None,
                     "yoy": pct(v[i], v[i - 4]) if i >= 4 else None})
    opm = row(q, "opm")
    margin = None
    if opm and opm[i] is not None and not fin:
        margin = {"value": opm[i], "yoy_pts": round(opm[i] - opm[i - 4], 1) if i >= 4 and opm[i - 4] is not None else None,
                  "qoq_pts": round(opm[i] - opm[i - 1], 1) if i >= 1 and opm[i - 1] is not None else None}
    return {"quarter": q["cols"][i], "prev": q["cols"][i - 1] if i >= 1 else None,
            "year_ago": q["cols"][i - 4] if i >= 4 else None, "rows": rows, "margin": margin,
            "basis": "Consolidated" if co.get("consolidated") else "Standalone", "unit": "₹ cr",
            "note": "EBITDA = operating profit before other income" if not fin else
                    "Lender: EBITDA does not apply, so revenue, PBT and PAT are shown"}


def _years(tbl):
    """Indices of full fiscal-year columns (drops TTM / half-year columns)."""
    cols = tbl.get("cols", [])
    idx = [i for i, c in enumerate(cols) if ym(c) and ym(c)[1] == 3]
    return idx or [i for i, c in enumerate(cols) if ym(c)]


def snapshot(co):
    r, p = co.get("ratios", {}), co["pnl"]
    ttm = len(p["cols"]) - 1 if p["cols"] and p["cols"][-1] == "TTM" else _last(row(p, "sales"))
    g = lambda k: (row(p, k)[ttm] if row(p, k) and ttm is not None else None)  # noqa: E731
    stats = [
        {"label": "Market cap", "value": r.get("market_cap"), "unit": "cr"},
        {"label": "Price", "value": r.get("current_price"), "unit": "rs"},
        {"label": "P/E", "value": r.get("stock_p_e"), "unit": "x"},
        {"label": "ROCE", "value": r.get("roce"), "unit": "%"},
        {"label": "ROE", "value": r.get("roe"), "unit": "%"},
        {"label": "Revenue, last 12m", "value": g("sales"), "unit": "cr"},
        {"label": "PAT, last 12m", "value": g("net_profit"), "unit": "cr"},
        {"label": "EBITDA margin", "value": None if co.get("is_financial") else g("opm"), "unit": "%"},
    ]
    return {"key": "snapshot", "title": "Financial snapshot", "stats": [s for s in stats if s["value"] is not None],
            "headline": headline(co)}


def trajectory(co):
    p = co["pnl"]
    yi = _years(p)[-6:]
    if len(yi) < 2:
        return None
    cols = [p["cols"][i] for i in yi]
    pick = lambda k: [row(p, k)[i] if row(p, k) else None for i in yi]  # noqa: E731
    rev, pat, opm = pick("sales"), pick("net_profit"), pick("opm")
    n = min(3, len(yi) - 1)
    rc, pc = cagr(rev, n), cagr(pat, n)
    dm = round(opm[-1] - opm[-1 - n], 1) if opm[-1] is not None and opm[-1 - n] is not None else None
    fin = co.get("is_financial")
    if fin:
        dm = None  # operating margin is not a meaningful measure for a lender
    q = co["quarters"]
    qs = row(q, "sales")
    mom = [pct(qs[i], qs[i - 4]) for i in range(max(4, len(qs) - 5), len(qs))] if len(qs) > 4 else []
    mom_cols = q["cols"][-len(mom):] if mom else []
    tone, bits = "neutral", []
    if rc is not None:
        bits.append(f"Revenue compounding {rc:g}% a year over {n} years")
    if pc is not None and rc is not None:
        if pc >= rc + 2:
            bits.append(f"profit faster at {pc:g}%"); tone = "good"
        elif pc <= rc - 2:
            bits.append(f"profit slower at {pc:g}%"); tone = "warn"
        else:
            bits.append(f"profit in step at {pc:g}%")
    if dm is not None and abs(dm) >= 1:
        bits.append(f"margin {'up' if dm > 0 else 'down'} {abs(dm):g} pt{'' if abs(dm) == 1 else 's'}")
        if dm <= -2:
            tone = "bad" if tone != "good" else "warn"
    clean = [m for m in mom if m is not None]
    if len(clean) >= 3:
        if clean[-1] < clean[0] - 3:
            bits.append(f"growth slowing: {clean[0]:g}% → {clean[-1]:g}% YoY over {len(clean)} quarters")
            tone = "warn" if tone in ("neutral", "good") else tone
        elif clean[-1] > clean[0] + 3:
            bits.append(f"growth accelerating: {clean[0]:g}% → {clean[-1]:g}% YoY")
    return {"key": "trajectory", "title": "Trajectory", "verdict": {"tone": tone, "text": "; ".join(bits) + "." if bits else ""},
            "stats": [{"label": f"Revenue CAGR, {n}y", "value": rc, "unit": "%"},
                      {"label": f"PAT CAGR, {n}y", "value": pc, "unit": "%"},
                      {"label": f"Margin change, {n}y", "value": dm, "unit": "pts"}],
            "series": {"labels": [c.replace("Mar 20", "FY") for c in cols],
                       "sets": [{"name": "Revenue", "values": rev, "unit": "cr"},
                                {"name": "PAT", "values": pat, "unit": "cr"},
                                ] + ([] if fin else [{"name": "Margin", "values": opm, "unit": "%"}])},
            "momentum": {"labels": mom_cols, "values": mom}}


def balance(co):
    b, p, rt = co["balance"], co["pnl"], co.get("ratios_tbl") or {}
    yi = _years(b)[-6:]
    if not yi:
        return None
    li = _last(row(b, "borrowings")) if row(b, "borrowings") else yi[-1]
    use = yi if li in yi else yi + [li]
    cols = [b["cols"][i] for i in use]
    pick = lambda k: [row(b, k)[i] if row(b, k) else None for i in use]  # noqa: E731
    debt = pick("borrowings")
    eq = [(a or 0) + (c or 0) if a is not None or c is not None else None for a, c in zip(pick("equity_capital"), pick("reserves"))]
    de = [round(d / e, 2) if d is not None and e else None for d, e in zip(debt, eq)]
    if co.get("is_financial"):
        dep = pick("deposits")
        return {"key": "balance", "title": "Balance sheet",
                "verdict": {"tone": "neutral", "text": "A lender: debt-to-equity and working-capital days do not apply. "
                            "Funding growth is shown instead; asset quality sits in the filings."},
                "stats": [{"label": "Net worth", "value": eq[-1], "unit": "cr"},
                          {"label": "Deposits", "value": dep[-1], "unit": "cr"},
                          {"label": "Borrowings", "value": debt[-1], "unit": "cr"}],
                "series": {"labels": cols, "sets": [{"name": "Net worth", "values": eq, "unit": "cr"},
                                                    {"name": "Borrowings", "values": debt, "unit": "cr"}]}}
    py = _years(p)
    icov = None
    if py:
        i = py[-1]
        intr, pbt = (row(p, "interest") or [None])[i if row(p, "interest") else 0], (row(p, "pbt") or [None])[i if row(p, "pbt") else 0]
        if intr and pbt is not None:
            icov = round((pbt + intr) / intr, 1)
    ry = _years(rt)[-6:] if rt.get("cols") else []
    ccc = [row(rt, "ccc")[i] for i in ry] if row(rt, "ccc") else []
    wcd = [row(rt, "working_capital_days")[i] for i in ry] if row(rt, "working_capital_days") else []
    tone, bits = "neutral", []
    d0 = de[-1]
    if d0 is not None:
        if d0 < 0.1:
            bits.append("Effectively debt-free"); tone = "good"
        elif d0 < 0.5:
            bits.append(f"Lightly geared at {d0:g}× debt-to-equity"); tone = "good"
        elif d0 < 1.2:
            bits.append(f"Moderate leverage at {d0:g}× debt-to-equity")
        else:
            bits.append(f"Heavily geared at {d0:g}× debt-to-equity"); tone = "bad"
        prior = next((x for x in de[-4:-1] if x is not None), None)
        if prior is not None and d0 - prior >= 0.15:
            bits.append(f"up from {prior:g}×"); tone = "warn" if tone == "good" else tone
        elif prior is not None and prior - d0 >= 0.15:
            bits.append(f"down from {prior:g}×")
    if icov is not None and icov < 3:
        bits.append(f"interest covered only {icov:g}×"); tone = "bad"
    cc = [c for c in ccc if c is not None]
    if len(cc) >= 3 and cc[-1] - cc[-3] >= 10:
        bits.append(f"cash cycle lengthened {cc[-3]:g} → {cc[-1]:g} days"); tone = "warn" if tone != "bad" else tone
    elif len(cc) >= 3 and cc[-3] - cc[-1] >= 10:
        bits.append(f"cash cycle shortened {cc[-3]:g} → {cc[-1]:g} days")
    return {"key": "balance", "title": "Balance sheet", "verdict": {"tone": tone, "text": "; ".join(bits) + "." if bits else ""},
            "stats": [{"label": "Borrowings", "value": debt[-1], "unit": "cr"},
                      {"label": "Debt / equity", "value": d0, "unit": "x"},
                      {"label": "Interest cover", "value": icov, "unit": "x"},
                      {"label": "Cash conversion cycle", "value": cc[-1] if cc else None, "unit": "days"},
                      {"label": "Working capital", "value": next((w for w in wcd[::-1] if w is not None), None), "unit": "days"}],
            "series": {"labels": [c.replace("Mar 20", "FY") for c in cols],
                       "sets": [{"name": "Debt / equity", "values": de, "unit": "x"},
                                {"name": "Borrowings", "values": debt, "unit": "cr"}]}}


def cash(co):
    c, p = co["cashflow"], co["pnl"]
    ci = _years(c)[-6:]
    if not ci or not row(c, "cfo"):
        return None
    cols = [c["cols"][i] for i in ci]
    pmap = {col: i for i, col in enumerate(p["cols"])}
    cfo = [row(c, "cfo")[i] for i in ci]
    fcf = [row(c, "fcf")[i] if row(c, "fcf") else None for i in ci]
    pat = [row(p, "net_profit")[pmap[col]] if col in pmap and row(p, "net_profit") else None for col in cols]
    pairs = [(a, b) for a, b in zip(cfo, pat) if a is not None and b is not None][-5:]
    conv = round(sum(a for a, _ in pairs) / sum(b for _, b in pairs), 2) if pairs and sum(b for _, b in pairs) > 0 else None
    yearly = [round(a / b, 2) if a is not None and b and b > 0 else None for a, b in zip(cfo, pat)]
    neg = sum(1 for f in fcf[-5:] if f is not None and f < 0)
    if co.get("is_financial"):
        v = {"tone": "neutral", "text": "A lender's operating cash flow tracks loan growth, not earnings quality, so the conversion test is not applied."}
    elif conv is None:
        v = {"tone": "neutral", "text": ""}
    else:
        n = len(pairs)
        if conv >= 0.9:
            v = {"tone": "good", "text": f"Profits turn into cash: ₹{conv:.2f} of operating cash for every ₹1 of PAT over {n} years"}
        elif conv >= 0.7:
            v = {"tone": "warn", "text": f"Partial conversion: ₹{conv:.2f} of operating cash per ₹1 of PAT over {n} years"}
        else:
            v = {"tone": "bad", "text": f"Weak conversion: only ₹{conv:.2f} of operating cash per ₹1 of PAT over {n} years"}
        ys = [y for y in yearly if y is not None]
        if len(ys) >= 3 and ys[-1] < ys[-3] - 0.2:
            v["text"] += f", and worsening ({ys[-3]:.2f} → {ys[-1]:.2f})"
            v["tone"] = "bad" if v["tone"] == "warn" else "warn" if v["tone"] == "good" else v["tone"]
        if neg >= 3:
            v["text"] += f"; free cash flow negative in {neg} of the last {len(fcf[-5:])} years"
        v["text"] += "."
    return {"key": "cash", "title": "Cash quality", "verdict": v,
            "stats": [{"label": "Cash conversion, 5y", "value": conv, "unit": "x"},
                      {"label": "Operating cash, latest", "value": cfo[-1], "unit": "cr"},
                      {"label": "Free cash flow, latest", "value": fcf[-1], "unit": "cr"}],
            "series": {"labels": [c.replace("Mar 20", "FY") for c in cols],
                       "sets": [{"name": "Operating cash", "values": cfo, "unit": "cr"},
                                {"name": "PAT", "values": pat, "unit": "cr"},
                                {"name": "Free cash flow", "values": fcf, "unit": "cr"}]}}


def cards(co):
    return [c for c in (snapshot(co), trajectory(co), balance(co), cash(co)) if c]
