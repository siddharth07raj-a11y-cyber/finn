"""Said vs did: what management guided, and what the statements then showed.

Division of labour that keeps numbers honest:
  1. EXTRACT  - turn transcript sentences into structured promises
                {metric, low, high, period, quote, page}. A cheap model does this when
                one is configured; otherwise a regex extractor handles explicit numeric
                guidance. Each transcript is processed once and cached forever.
  2. EVALUATE - plain code compares each promise with the reported numbers for that
                period. No model ever computes or judges a figure.
"""
import re

from . import cache, llm
from .analytics import ym, row, MONTHS

METRICS = {"revenue_growth": "Revenue growth", "ebitda_margin": "EBITDA margin", "ebit_margin": "Operating (EBIT) margin", "margin": "Margin (type not stated)", "pat_growth": "PAT growth",
           "capex": "Capex", "other": "Other"}
CUE = re.compile(r"guid|\bexpect|target|\baim|outlook|confident|reiterat|should be|will be|look(ing)? (at|to|ahead)|on track|\bplan|going forward", re.I)
# Words that mark a number as something already reported rather than promised.
PAST = re.compile(r"\b(maintained|delivered|reported|achieved|recorded|posted|registered|clocked|was|were|came in|stood at|grew|declined|"
                  r"improved|expanded|contracted|increased|decreased|rose|fell|incurred|spent|has been|have been|had)\b|"
                  r"(during|for|in) the (quarter|year|half)|this quarter|last (quarter|year)|year[- ]on[- ]year|\byoy\b|\bqoq\b|sequential", re.I)
NUM = r"(\d{1,3}(?:\.\d+)?)"
RANGE = re.compile(NUM + r"\s*(?:%|per ?cent)?\s*(?:-|–|—|to)\s*" + NUM + r"\s*(?:%|per ?cent)", re.I)
SINGLE = re.compile(r"(?:around|about|approximately|at least|of|at|~)?\s*" + NUM + r"\s*(?:%|per ?cent)", re.I)
CRORE = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|billion|bn\b)", re.I)
FY = re.compile(r"\bFY\s?'?(\d{2,4})(?:\s?-\s?(\d{2}))?\b|\bfiscal(?: year)? (\d{4})\b", re.I)
QTR = re.compile(r"\bQ([1-4])\s?FY\s?'?(\d{2,4})\b", re.I)


def call_fy(date_label):
    """Fiscal year in progress at the time of a call, e.g. 'Jul 2026' -> 2027."""
    p = date_label.split()
    y, m = int(p[1]), MONTHS[p[0]]
    return y + 1 if m >= 4 else y


def _fy(s, default):
    m = FY.search(s)
    if not m:
        if re.search(r"next (fiscal|financial)? ?year", s, re.I):
            return default + 1, True
        return default, True
    if m.group(3):
        return int(m.group(3)), False
    y = int(m.group(1))
    if m.group(2):  # FY2026-27
        return (y // 100 * 100 if y > 100 else 2000) + int(m.group(2)), False
    return (y if y > 100 else 2000 + y), False


def _metric(s):
    lo = s.lower()
    if re.search(r"capex|capital expenditure", lo):
        return "capex"
    if re.search(r"ebitda", lo) and re.search(r"margin", lo):
        return "ebitda_margin"
    if re.search(r"(operating|ebit) margin|\bopm\b", lo):
        return "ebit_margin"  # "operating margin" in Indian filings is after depreciation
    if re.search(r"margin", lo):
        return "margin"  # gross? net? not stated: shown, not graded
    if re.search(r"(pat|net profit|profit after tax|earnings|bottom.?line)\b.{0,40}grow|grow.{0,40}(pat|net profit|earnings)\b", lo):
        return "pat_growth"
    if re.search(r"(revenue|top.?line|sales|volume).{0,60}(grow|increase)|grow.{0,60}(revenue|top.?line|sales|volume)", lo):
        return "revenue_growth"
    return None


SPEAKER = re.compile(r"^((?:Mr|Ms|Mrs|Dr)?\.? ?[A-Z][A-Za-z.'\-]*(?: [A-Z&][A-Za-z.'\-]*){0,4}):\s*(.*)$")
NOT_MGMT = re.compile(r"moderator|operator|analyst|participant|questioner|investor", re.I)


def turns(pages):
    """Yield (page, speaker, text) for each stretch of speech. PDF text is hard-wrapped, so
    lines are re-joined into paragraphs; the speaker carries across page breaks."""
    speaker = None
    for pno, text in enumerate(pages, 1):
        buf = []
        for line in re.sub(r"-\n(?=[a-z])", "", text).split("\n"):
            line = line.strip()
            if re.search(r"\bPage \d+ of \d+\b", line, re.I):  # running header / footer
                line = "" if len(line) < 90 else re.sub(r"\bPage \d+ of \d+\b", " ", line, flags=re.I)
            m = SPEAKER.match(line)
            if m and len(m.group(1)) <= 45:
                if buf:
                    yield pno, speaker, " ".join(buf)
                speaker, buf = m.group(1).strip(), [m.group(2)]
            elif line:
                buf.append(line)
        if buf:
            yield pno, speaker, " ".join(buf)


def analysts(pages):
    """Surnames of people the moderator introduces as callers ("from the line of X from Y")."""
    text = " ".join(pages).replace("\n", " ")
    names = re.findall(r"line of\s+(?:Mr|Ms|Mrs|Dr)?\.?\s*([A-Z][A-Za-z.' \-]{2,40}?)\s+(?:from|of|with|at)\b", text)
    return {n.split()[-1].lower() for n in names if n.split()}


SCOPES = [("segment", r"\bsegment|\bFMEG\b|\bdivision\b|\bvertical\b|business unit|this business|\bEMS\b|\bB2[BC]\b"),
          ("quarterly", r"quarter[- ]?on[- ]?quarter|\bqoq\b|sequential|next quarter|coming quarter|\bQ[1-4]\b"),
          ("long term", r"long[- ]?term|medium[- ]?term|over the next (few|two|three|four|five|\d+) years|next (few|two|three|four|five|\d+) years")]


def _scope(s, metric):
    """Label a statement for what it actually covers. Anything narrower or longer than a
    company-level fiscal-year number gets a qualifier and is not graded."""
    label = METRICS[metric]
    quals = [name for name, rx in SCOPES if re.search(rx, s, re.I)]
    if metric == "revenue_growth" and re.search(r"volume", s, re.I) and not re.search(r"revenue|top.?line|\bsales\b", s, re.I):
        label = "Volume growth"
        quals = quals or ["volume"]
    if not quals:
        return None, False
    quals = [q for q in quals if q != "volume"]
    return label + (f" ({', '.join(quals)})" if quals else ""), True


def regex_extract(pages, said_on, url):
    """Explicit numeric guidance stated by management. Skips questions and anything said by
    a caller, so an analyst's own number is never recorded as a company promise."""
    out, dfy, callers = [], call_fy(said_on), analysts(pages)
    for pno, speaker, text in turns(pages):
        if speaker and (NOT_MGMT.search(speaker) or speaker.split()[-1].lower() in callers):
            continue
        for s in re.split(r"(?<=[.?!])\s+", text):
            s = s.strip()
            if len(s) < 25 or len(s) > 420 or s.endswith("?") or not CUE.search(s):
                continue
            if re.match(r"(?:so,? |and,? |but,? |just,? )*(?:do|does|did|can|could|would|will|is|are|should|what|how|when|where|why|any)\b", s, re.I):
                continue  # a question whose question mark fell in a later sentence
            metric = _metric(s)
            if not metric:
                continue
            lo = hi = None
            unit = "pct"
            if metric == "capex":
                m = CRORE.search(s)
                if not m:
                    continue
                lo = hi = float(m.group(1).replace(",", "")) * (100 if m.group(2).lower().startswith("b") else 1)
                unit = "cr"
            else:
                m = RANGE.search(s)
                if m:
                    lo, hi = float(m.group(1)), float(m.group(2))
                else:
                    m = SINGLE.search(s)
                    if not m:
                        continue
                    lo = hi = float(m.group(1))
                if lo > hi or hi > 100:
                    continue
            if PAST.search(s[max(0, m.start() - 140):m.start()]):
                continue  # the words leading up to the number describe a result, not a promise
            fy, assumed = _fy(s, dfy)
            label, scope = _scope(s, metric)
            if scope:
                metric = "other"  # not a company-level, full-year headline number: shown, never graded
            quote = s if len(s) <= 260 else ("…" if m.start() > 150 else "") + s[max(0, m.start() - 150):m.end() + 100].strip() + "…"
            out.append({"metric": metric, "label": label, "lo": lo, "hi": hi, "unit": unit, "fy": fy, "fy_assumed": assumed,
                        "said_on": said_on, "quote": quote, "page": pno, "url": url, "by": "rules"})
    return out


SYSTEM = """You extract management guidance from one earnings-call transcript of an Indian listed company.
Use ONLY the text provided. Return forward-looking statements by MANAGEMENT (never analysts or the moderator) that put a number on a metric.
Output JSON: {"items":[{"metric":"revenue_growth|ebitda_margin|ebit_margin|pat_growth|capex|other","label":"short plain name, required when metric is other",
"lo":number,"hi":number,"unit":"pct|cr","fy":2027,"fy_stated":true,"quote":"verbatim sentence, max 40 words","page":3}]}
fy_stated is true ONLY if the speaker names the year or says "this year"/"current fiscal"/"full year"; otherwise false.
Use revenue_growth / ebitda_margin / ebit_margin / pat_growth ONLY for guidance about the WHOLE COMPANY for a FULL fiscal year.
 - ebitda_margin only if the text says EBITDA. "Operating margin" or "EBIT margin" is ebit_margin.
 - Anything narrower or different is metric "other" with a label that says what it is: a segment or product line, volume growth,
   a single quarter or an exit rate, a long-term or aspirational band, gross margin, order book, market share, etc.
Do NOT return results already achieved ("we delivered 25%", "capex incurred was...") - only what is promised or expected.
lo=hi for a point estimate. fy is the Indian fiscal year the guidance is FOR (FY27 = year ending March 2027); if the text says
"this year" use {fy}. Growth and margins in percent (150 basis points = 1.5), capex in Rs crore (1 billion = 100 crore). Skip anything without a number.
If there is no numeric guidance return {"items":[]}."""


GRADED = ("revenue_growth", "ebitda_margin", "ebit_margin", "pat_growth")
AMOUNT = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:-|–|to)?\s*(?:(?:rs\.?|inr|₹)\s*)?([\d,]+(?:\.\d+)?)?\s*(?:odd\s+)?(lakh crore|crore|cr\b|billion|bn\b|million|mn\b)", re.I)
RANGE_AMT = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:(?:lakh crore|crore|cr\b|billion|bn\b|million|mn\b)s?)?\s*(?:-|–|to)\s*(?:(?:rs\.?|inr|₹)\s*)?([\d,]+(?:\.\d+)?)\s*(?:odd\s+)?(lakh crore|crore|cr\b|billion|bn\b|million|mn\b)", re.I)
TO_CRORE = {"lakh crore": 1e5, "crore": 1, "cr": 1, "billion": 100, "bn": 100, "million": 0.1, "mn": 0.1}


def _guard(it, cfy):
    """Code-side checks on what a model extracted. The model proposes; these rules decide
    what may be graded, and re-derive money amounts from the quote itself."""
    q = it.get("quote") or ""
    if it["unit"] == "pct" and re.search(r"basis points?|\bbps\b", q, re.I) and it["lo"] >= 5:
        it["lo"], it["hi"] = it["lo"] / 100, it["hi"] / 100
    if it["unit"] == "cr":
        vals = []
        found = AMOUNT.findall(q)
        ranges = [f for f in found if f[1]] or [f for f in RANGE_AMT.findall(q)]
        # a quote often mentions money already spent before the target: prefer the stated range, else the last amount
        for a, b, unit in (ranges[-1:] or found[-1:]):
            k = TO_CRORE[unit.lower()]
            vals += [float(x.replace(",", "")) * k for x in (a, b) if x and x.replace(",", "").replace(".", "")]
        if vals:
            it["lo"], it["hi"] = min(vals), max(vals)
        elif it["hi"] > 1e7:  # given in rupees
            it["lo"], it["hi"] = it["lo"] / 1e7, it["hi"] / 1e7
    if it["unit"] == "pct" and not re.search(r"%|per ?cent|basis points?|\bbps\b", q, re.I):
        it["unit"] = "num"  # a count or quantity (units, volumes), not a percentage
        if it["metric"] in GRADED:
            it["metric"], it["label"] = "other", it.get("label") or METRICS[it["metric"]]
    # a margin is only called EBITDA or EBIT if the speaker's own words say so
    if it["metric"] == "ebitda_margin" and not re.search(r"ebitda", q, re.I):
        it["metric"] = "margin"
    if it["metric"] == "ebit_margin" and not re.search(r"operating margin|\bebit\b|\bopm\b", q, re.I):
        it["metric"] = "margin"
    if it["metric"] in GRADED:
        quals = [name for name, rx in SCOPES if re.search(rx, q, re.I)]
        if it["fy"] >= cfy + 2 and "long term" not in quals:
            quals.append("long term")
        if quals:  # narrower or longer than a company-level fiscal-year number
            it["label"] = f"{METRICS[it['metric']]} ({', '.join(quals)})"
            it["metric"] = "other"
    if it.get("label"):
        it["label"] = re.sub(r"[,\s]*\bFY\s?'?\d{2,4}\b\s*$", "", it["label"]).strip() or it["label"]
    return it


def llm_extract(pages, said_on, url):
    # Token discipline: send only pages that contain guidance-like language.
    keep = [(i + 1, p) for i, p in enumerate(pages) if p and re.search(r"guid|expect|target|outlook|capex|margin", p, re.I)]
    if not keep:
        return []
    text = "\n\n".join(f"[page {n}]\n{p[:6000]}" for n, p in keep)[:60000]
    res = llm.chat_json("cheap", SYSTEM.replace("{fy}", str(call_fy(said_on))), f"Call held: {said_on}\n\n{text}", max_tokens=2000)
    if not isinstance(res, dict):
        return None
    out = []
    for it in res.get("items", []):
        try:
            metric = it["metric"] if it.get("metric") in METRICS else "other"
            lo, hi = float(it["lo"]), float(it.get("hi", it["lo"]))
            label = (str(it.get("label") or "Other target").strip()[:60]) if metric == "other" else None
            label = label[0].upper() + label[1:] if label else None
            out.append({"metric": metric, "label": label, "lo": min(lo, hi), "hi": max(lo, hi),
                        "unit": it.get("unit", "pct"), "fy": int(it.get("fy") or call_fy(said_on)),
                        "fy_assumed": it.get("fy_stated") is False or not it.get("fy"),
                        "said_on": said_on, "quote": str(it.get("quote", ""))[:300], "page": it.get("page"),
                        "url": url, "by": "model"})
            _guard(out[-1], call_fy(said_on))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def extract(pages, said_on, url):
    """Promises from one transcript; cached forever (a transcript never changes)."""
    key = f"guid9:{'m' if llm.ready() else 'r'}:{url}"
    hit, _ = cache.get(key)
    if hit is not None:
        return hit
    items = llm_extract(pages, said_on, url) if llm.ready() else None
    if items is None:
        items = regex_extract(pages, said_on, url)
    if not url.startswith("sample://"):
        cache.put(key, items)
    return items


# ---- evaluation: pure arithmetic ----------------------------------------------------
def _fy_quarters(q, fy):
    """Column indices of the quarters of fiscal year `fy` that have been reported."""
    want = [(fy - 1, 6), (fy - 1, 9), (fy - 1, 12), (fy, 3)]
    cols = [ym(c) for c in q["cols"]]
    return [cols.index(w) for w in want if w in cols and row(q, "sales")[cols.index(w)] is not None]


def _period_name(n, fy):
    return {1: "Q1", 2: "H1", 3: "9M"}.get(n, "") + f" FY{fy % 100}"


def actual(co, metric, fy):
    """Reported value for a metric over fiscal year `fy`: full year if complete, else year-to-date."""
    q, p = co["quarters"], co["pnl"]
    pcols = [ym(c) for c in p["cols"]]
    key = {"revenue_growth": "sales", "pat_growth": "net_profit"}.get(metric)
    is_margin = metric in ("ebitda_margin", "ebit_margin")

    def profit(tbl, i):
        o = row(tbl, "operating_profit")[i] if row(tbl, "operating_profit") else None
        if o is None or metric == "ebitda_margin":
            return o
        d = row(tbl, "depreciation")[i] if row(tbl, "depreciation") else None
        return None if d is None else o - d  # EBIT = operating profit - depreciation

    if (fy, 3) in pcols and (is_margin or (fy - 1, 3) in pcols):
        i = pcols.index((fy, 3))
        if is_margin:
            s, o = row(p, "sales")[i], profit(p, i)
            return (round(100 * o / s, 1), f"FY{fy % 100}", True) if s and o is not None else None
        j = pcols.index((fy - 1, 3))
        a, b = row(p, key)[i], row(p, key)[j]
        return (round(100 * (a / b - 1), 1), f"FY{fy % 100}", True) if a is not None and b and b > 0 else None
    idx = _fy_quarters(q, fy)
    if not idx:
        return None
    done = len(idx) == 4
    if is_margin:
        s = sum(row(q, "sales")[i] for i in idx)
        parts = [profit(q, i) for i in idx]
        if not s or any(x is None for x in parts):
            return None
        return (round(100 * sum(parts) / s, 1), _period_name(len(idx), fy), done)
    if any(i < 4 for i in idx):
        return None
    cur = sum(row(q, key)[i] or 0 for i in idx)
    base = sum(row(q, key)[i - 4] or 0 for i in idx)
    return (round(100 * (cur / base - 1), 1), _period_name(len(idx), fy), done) if base > 0 else None


def evaluate(items, co):
    """Attach the reported figure and a verdict to each promise."""
    out = []
    for it in items:
        it = dict(it)
        it["label"] = it.get("label") or METRICS.get(it["metric"], "Other")
        it["actual"] = it["period"] = None
        it["verdict"] = "unverifiable"
        # Without a model, only grade a promise whose sentence names its fiscal year.
        gradeable = not it.get("fy_assumed")
        if gradeable and it["metric"] in GRADED and it["unit"] == "pct":
            got = actual(co, it["metric"], it["fy"])
            if got:
                val, period, done = got
                tol = 0.25
                it["actual"], it["period"], it["final"] = val, period, done
                if val < it["lo"] - tol:
                    it["verdict"] = "missed" if done else "behind"
                elif val > it["hi"] + tol:
                    it["verdict"] = "beat" if done else "ahead"
                else:
                    it["verdict"] = "met" if done else "on_track"
                it["gap"] = round(val - (it["lo"] if val < it["lo"] else it["hi"] if val > it["hi"] else val), 1)
            else:
                it["verdict"] = "pending"
        out.append(it)
    return out


def _order(label):
    y, m = ym(label) or (0, 0)
    return y * 12 + m


def scorecard(items):
    """Group promises by (metric, fiscal year) into threads, newest year first, and
    show how the guidance itself moved from call to call."""
    threads = {}
    for it in items:
        undated = bool(it.get("fy_assumed"))
        solo = (it["said_on"], it.get("page"), it["lo"], it["hi"]) if undated or it["metric"] in ("other", "margin") else None
        threads.setdefault((it["metric"], it["fy"], it["label"], solo), []).append(it)
    out = []
    for (metric, fy, label, _solo), its in threads.items():
        its.sort(key=lambda x: _order(x["said_on"]))
        dedup = []
        for it in its:  # one entry per call: keep the first statement of each range
            if not any(d["said_on"] == it["said_on"] and d["lo"] == it["lo"] and d["hi"] == it["hi"] for d in dedup):
                dedup.append(it)
        first, last = dedup[0], dedup[-1]
        moved = None  # a real revision moves outside the first range; narrowing inside it is not a cut
        if len(dedup) > 1:
            if last["lo"] < first["lo"] - 1e-9 and last["hi"] <= first["hi"]:
                moved = "cut"
            elif last["hi"] > first["hi"] + 1e-9 and last["lo"] >= first["lo"]:
                moved = "raised"
        out.append({"metric": metric, "label": label, "fy": fy, "unit": first["unit"], "said": dedup,
                    "year_stated": not first.get("fy_assumed"),
                    "actual": first.get("actual"), "period": first.get("period"), "final": first.get("final"),
                    "verdict_vs_first": first["verdict"], "verdict_vs_last": last["verdict"], "moved": moved})
    rank = {"revenue_growth": 0, "ebitda_margin": 1, "ebit_margin": 1, "pat_growth": 2, "capex": 3, "margin": 4, "other": 4}
    out.sort(key=lambda t: (rank.get(t["metric"], 9) >= 4, not t["year_stated"], -t["fy"], rank.get(t["metric"], 9)))
    checked = [t for t in out if t["verdict_vs_first"] in ("met", "beat", "missed", "on_track", "ahead", "behind")]
    kept = sum(1 for t in checked if t["verdict_vs_first"] in ("met", "beat", "on_track", "ahead"))
    cuts = sum(1 for t in checked if t["moved"] == "cut")
    # keep the page readable: every graded or pending thread, plus the most recent ungraded ones
    main = [t for t in out if t["verdict_vs_first"] != "unverifiable"]
    extra = sorted((t for t in out if t["verdict_vs_first"] == "unverifiable"), key=lambda t: -_order(t["said"][-1]["said_on"]))
    return {"threads": main + extra[:8], "more": max(0, len(extra) - 8), "checked": len(checked), "kept": kept, "cuts": cuts}


def read(sc):
    """One-line, rule-written reading of the scorecard."""
    if not sc["threads"]:
        return "FINN found no numeric guidance in the transcripts read."
    if not sc["checked"]:
        return "FINN found numeric targets, but none is a company-level, dated number it can grade against reported results."
    s = f"Kept {sc['kept']} of {sc['checked']} checkable promises against the first number given"
    if sc["cuts"]:
        s += f"; {sc['cuts']} of those {sc['checked']} {'was' if sc['cuts'] == 1 else 'were'} cut after first being given"
    return s + "."
