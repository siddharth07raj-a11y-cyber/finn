"""Turn a surfaced filing into something you can act on without opening the PDF.

  results            -> first cut: Revenue / EBITDA / PBT / PAT, QoQ and YoY
  management change  -> who is coming in: role, background, where they came from
  everything else    -> a one-line summary (the filing's own text, tightened)
"""
import re
from datetime import datetime
from urllib.parse import quote

from . import analytics, cache, llm, sources


def one_liner(item):
    body, title = item.get("body", ""), item.get("title", "")
    if len(body) < 25 or body.lower()[:60] == title.lower()[:60]:
        return ""
    s = re.split(r"(?<=[.;])\s", body)[0]
    return (s if len(s) > 40 else body)[:200].rstrip(" .;") + "."


# ---- results ----------------------------------------------------------------------
def expected_quarter(dt_iso):
    d = datetime.fromisoformat(dt_iso)
    y, m = d.year, ((d.month - 1) // 3) * 3
    return (y - 1, 12) if m == 0 else (y, m)


RES_SYSTEM = """You read the financial-results table of an Indian listed company's exchange filing.
Use ONLY the text given. Prefer the CONSOLIDATED statement if present, else standalone. Return JSON:
{"basis":"consolidated|standalone","unit":"crore|lakh|million|billion",
 "periods":[{"ended":"YYYY-MM-DD","revenue":0,"other_income":0,"finance_costs":0,"depreciation":0,"pbt":0,"pat":0}]}
Give exactly the three QUARTER columns: latest quarter, preceding quarter, and same quarter of the previous year.
revenue = revenue from operations; pbt = profit before tax (before exceptional items if both are shown);
pat = net profit after tax for the period. Copy numbers exactly; use null if a line is absent."""


def results_from_filing(item):
    """Headline numbers parsed from the filing PDF itself (used when the standardised
    tables have not caught up with a fresh filing). Returns None if not possible."""
    if not (llm.ready() and item.get("url")):
        return None
    try:
        pages = sources.doc_pages(item["url"])
    except Exception:  # noqa: BLE001
        return None
    hits = [(i, p) for i, p in enumerate(pages) if re.search(r"revenue from operations", p, re.I)
            and re.search(r"profit.{0,20}before.{0,20}tax", p, re.I | re.S)]
    if not hits:
        return None  # scanned PDF or no statement text
    hits.sort(key=lambda x: (0 if re.search(r"consolidated", x[1][:1500], re.I) else 1, x[0]))
    res = llm.chat_json("cheap", RES_SYSTEM, hits[0][1][:9000], max_tokens=700)
    try:
        per = sorted(res["periods"], key=lambda x: x["ended"], reverse=True)
        cur = per[0]
        prev = next((p for p in per[1:] if p["ended"][:4] == cur["ended"][:4] or int(p["ended"][5:7]) != int(cur["ended"][5:7])), None)
        yago = next((p for p in per[1:] if int(p["ended"][5:7]) == int(cur["ended"][5:7]) and p is not prev), None)
        k = {"crore": 1, "lakh": 0.01, "million": 0.1, "billion": 100}.get(str(res.get("unit", "crore")).lower(), 1)

        def ebitda(p):
            if p is None or p.get("pbt") is None:
                return None
            return (p["pbt"] + (p.get("finance_costs") or 0) + (p.get("depreciation") or 0) - (p.get("other_income") or 0)) * k

        def val(p, key):
            return None if p is None or p.get(key) is None else p[key] * k

        rows = []
        for key, label, fn in (("sales", "Revenue", lambda p: val(p, "revenue")), ("operating_profit", "EBITDA", ebitda),
                               ("pbt", "PBT", lambda p: val(p, "pbt")), ("net_profit", "PAT", lambda p: val(p, "pat"))):
            c = fn(cur)
            if c is None:
                continue
            rows.append({"key": key, "label": label, "value": round(c), "qoq": analytics.pct(c, fn(prev)),
                         "yoy": analytics.pct(c, fn(yago))})
        if len(rows) < 3 or not rows[0]["value"] or rows[-1]["value"] > rows[0]["value"]:
            return None  # sanity: profit cannot exceed revenue
        d = datetime.fromisoformat(cur["ended"])
        return {"quarter": d.strftime("%b %Y"), "rows": rows, "margin": None, "unit": "₹ cr",
                "basis": str(res.get("basis", "")).capitalize(), "page": hits[0][0] + 1,
                "note": "Read from the filing; EBITDA = PBT + finance costs + depreciation − other income"}
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def results(item):
    want = expected_quarter(item["dt"])
    try:
        co, _ = sources.company(item["symbol"])
        h = analytics.headline(co)
    except Exception:  # noqa: BLE001
        h = None
    if h and analytics.ym(h["quarter"]) == want:
        return {"kind": "results", "status": "ok", "source": co["source"], **h}
    parsed = results_from_filing(item)
    if parsed:
        return {"kind": "results", "status": "ok", "source": "the filing", **parsed}
    if h:
        return {"kind": "results", "status": "lagging", "source": co["source"], **h,
                "note": f"The filing's numbers are not in the standardised tables yet. Showing {h['quarter']}; open the filing for the new quarter."}
    return {"kind": "results", "status": "unavailable"}


# ---- management change --------------------------------------------------------------
NAME = r"(?:Mr|Ms|Mrs|Dr|Shri|Smt|Prof)\.? (?:[A-Z][\w.'\-]*\.? ?){1,4}"
ROLE = r"(Managing Director(?: (?:and|&) (?:CEO|Chief Executive Officer))?|Chief Executive Officer|Chief Financial Officer|Chief Operating Officer|Chief Technology Officer|Whole.?[Tt]ime Director|Executive Director|Independent Director|Non.?Executive Director|Additional Director|Chairman|Chairperson|Company Secretary|CEO|CFO|COO)"
ACTIONS = [("resigned", r"resign|stepp?(ed|ing)? down|tendered"), ("retired", r"retire|superannuat"),
           ("ceased", r"cessation|ceased|demise"), ("appointed", r"appoint|elevat|designat|induct")]
MGMT_SYSTEM = """You read an Indian stock-exchange filing about a change in directors or key management.
Use ONLY the text given. Return JSON: {"changes":[{"name":"...","role":"...","action":"appointed|resigned|retired|ceased|re-appointed",
"effective":"date or empty","reason":"stated reason, or empty","bio":["up to 3 short facts: previous employer and role, years of experience, education"]}]}
bio only for people joining or being appointed, and only from the text. No speculation."""


BOILER = re.compile(r"(viz\.?,?\s*)?appointment,?\s*re-?appointment,?\s*resignation,?\s*removal,?\s*death\s*(or\s*otherwise)?"
                    r"|\(in case of appointment[^)]*\)|appointment\s*/\s*(re-?appointment\s*/\s*)?cessation", re.I)
NOUN_ACTION = {"appointment": "appointed", "re-appointment": "re-appointed", "reappointment": "re-appointed", "elevation": "appointed",
               "induction": "appointed", "resignation": "resigned", "retirement": "retired", "superannuation": "retired", "cessation": "ceased"}
NOT_NAME = {"additional", "independent", "director", "managing", "chief", "executive", "chairman", "chairperson", "non", "whole",
            "company", "key", "senior", "group", "president", "vice", "head", "the", "and", "limited", "ltd", "bank", "as", "an", "a"}
POINTER = re.compile(r"^\W*(as (provided|per|enclosed|attached)|refer|please|annexure|enclosed|attached|given (in|below)|not applicable|n\.?a\.?\b)", re.I)
BIO_WORDS = re.compile(r"experience|years|chartered|\bmba\b|graduate|degree|served|worked|joined|holds|previously|prior to|career|alumn|fellow|institute", re.I)


def _mgmt_rules(text):
    """Model-free reading of a SEBI Regulation 30 disclosure. These filings are tables full of
    template wording ("appointment, re-appointment, resignation, removal..."), so the action is
    taken only from the words right next to a person's name. Prefers saying nothing to guessing."""
    text = re.sub(r"\b(Mr|Ms|Mrs|Dr|Smt|Prof)\.", r"\1", text)  # honorific dots are not sentence ends
    text = BOILER.sub(" ", text)
    changes, seen = [], set()
    for m in re.finditer(NAME, text):
        parts = m.group(0).strip(" .,").split()
        while len(parts) > 1 and re.split(r"[-.]", parts[-1].lower())[0] in NOT_NAME:
            parts.pop()
        if len(parts) < 3:  # honorific + at least two name parts
            continue
        name = " ".join(parts)
        key = re.sub(r"[^a-z]", "", name.lower())
        before, after = text[max(0, m.start() - 70):m.start()], re.split(r"(?<=[a-z]{3}\.)\s", text[m.end() - 1:m.end() + 130])[0]
        mb = re.search(r"(re-?appointment|appointment|elevation|induction|resignation|retirement|superannuation|cessation)\s+of\s*$", before, re.I)
        act = NOUN_ACTION[mb.group(1).lower()] if mb else next((a for a, rx in ACTIONS if re.search(rx, after, re.I)), None)
        if not act or key in seen:
            continue
        seen.add(key)
        role = re.search(ROLE, after) or re.search(ROLE, before)
        changes.append({"name": name, "role": role.group(1) if role else "", "action": act, "effective": "", "reason": "", "bio": []})
    # the profile is often a pointer ("As provided in Annexure II"); skip pointers and take the real paragraph
    for m in re.finditer(r"(?:brief\s+(?:profile|resume)|profile\s+of)[^:\n]{0,80}[:\n]?\s*", text, re.I):
        para = re.split(r"\n\s*\n|Disclosure of relationship", text[m.end():m.end() + 1400], flags=re.I)[0]
        para = re.sub(r"\s+", " ", para).strip()
        if POINTER.search(para) or len(para) < 80 or not BIO_WORDS.search(para):
            continue
        bio = [b.strip() for b in re.split(r"(?<=[a-z0-9)]{2}\.)\s+(?=[A-Z])", para) if len(b.strip()) > 25][:3]
        ins = [c for c in changes if c["action"] in ("appointed", "re-appointed")]
        who = next((c for c in ins if c["name"].split()[-1] in text[m.start():m.end() + 300]), None) or (ins[0] if ins else None)
        if who and bio:
            who["bio"] = [b[:260] for b in bio]
        break
    return changes


def management(item):
    text = f"{item['title']}. {item.get('body', '')}"
    pages, doc_ok = [], False
    if item.get("url"):
        try:
            pages = sources.doc_pages(item["url"])[:6]
            doc_ok = sum(len(p) for p in pages) > 200
        except Exception:  # noqa: BLE001
            pages = []
    full = text + "\n" + "\n".join(pages)
    changes = None
    if llm.ready():
        res = llm.chat_json("cheap", MGMT_SYSTEM, full[:14000], max_tokens=800)
        if isinstance(res, dict) and isinstance(res.get("changes"), list):
            changes = [c for c in res["changes"] if isinstance(c, dict) and c.get("name")]
    if changes is None:
        changes = _mgmt_rules(full)
    for c in changes:
        c["bio"] = [str(b) for b in (c.get("bio") or [])][:3]
        q = quote(re.sub(r"^(Mr|Ms|Mrs|Dr|Shri|Smt|Prof)\.? ", "", c["name"]) + " " + item.get("company", ""))
        c["linkedin"] = f"https://www.linkedin.com/search/results/people/?keywords={q}"
    changes.sort(key=lambda c: 0 if c.get("action") in ("appointed", "re-appointed") else 1)
    return {"kind": "management", "status": "ok" if changes else "unavailable", "changes": changes[:4],
            "source": "the filing" if doc_ok else "the filing's summary",
            "note": "" if doc_ok or not item.get("url") else "The filing PDF has no readable text (scanned); showing what the summary states."}


def kind_for(cls):
    if cls["category"] == "results" and cls["subtype"] == "filing":
        return "results"
    if cls["category"] == "management_change":
        return "management"
    return None


def enrich(item, cls):
    kind = kind_for(cls)
    if not kind:
        return None
    key = f"enr:{item['id']}"
    hit, _ = cache.get(key, ttl=None if not sources.SAMPLE else 0)
    if hit:
        return hit
    out = results(item) if kind == "results" else management(item)
    if out.get("status") == "ok" and not sources.SAMPLE:
        cache.put(key, out)
    return out
