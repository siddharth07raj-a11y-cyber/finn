"""Filing -> category, sub-type and a base materiality score.

Rules first: exchange filings are formulaic, so ordered regexes settle the large
majority at zero cost. Only filings the rules cannot place (vague "Updates" /
"General updates" subjects) are sent - in one batch, titles only - to the cheap model.
Categories follow the reference document's taxonomy.
"""
import re

from . import cache, llm

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]
LABEL = {"results": "Results", "M&A": "M&A", "fund_raise": "Fund raise", "management_change": "Management",
         "litigation": "Legal & regulatory", "insider_trading": "Insider trades", "earnings_call": "Earnings call",
         "investor_meetings": "Investor meetings", "credit_rating": "Credit rating", "dividend": "Dividend",
         "bonus_split": "Bonus / split", "capex": "Capex", "press_release": "Company news",
         "postal_ballot": "Postal ballot", "agm_egm": "AGM / EGM", "pledging": "Pledging",
         "unclassified": "Routine paperwork"}

# (category, sub-type, base score, pattern) - first match wins, so order is the logic.
RULES = [
    ("unclassified", "routine", 5, r"newspaper|trading window|duplicate.{0,3}share|loss of share|\besops?\b|esos|esps|stock options?|74\s*\(5\)|depositories and participants|brsr|business responsibility|secretarial audit|\biepf\b|compliance certificate|investor complaints|statement of deviation|registrar|book closure|statutory auditor|company secretary|compliance officer|reg(ulation)?\.? ?40\b"),
    ("postal_ballot", "ballot", 12, r"postal ballot"),
    ("agm_egm", "meeting", 12, r"\bagm\b|\begm\b|annual general meeting|extra.?ordinary general|proceedings of|voting results|scrutini[sz]er"),
    ("earnings_call", "transcript", 30, r"transcript"),
    ("earnings_call", "call", 18, r"audio|video recording|earnings (conference )?call|conference call"),
    ("results", "deck", 30, r"(investor|earnings|results?) presentation"),
    ("investor_meetings", "meet", 8, r"analysts?\b|institutional investor|investor meet|investor conference|road ?show|plant visit"),
    ("fund_raise", "proposal", 62, r"(board meeting|intimation).{0,80}(fund ?rais|raising of funds|qip|qualified institutional|rights issue|preferential|buy-?back)"),
    ("press_release", "update", 40, r"reference to the (financial )?results|results? (issued|announced|declared|published) by|results of (the |its )?(holding|parent|promoter|subsidiar)"),
    ("results", "upcoming", 32, r"(intimation|notice) .{0,60}(results?|board meeting)|board meeting intimation"),
    ("results", "filing", 90, r"financial results?|quarterly results?|results? for the (quarter|half|year|period)|un-?audited|audited (standalone|consolidated)"),
    ("results", "release", 45, r"\bq[1-4]\b.{0,12}(fy|results)|results"),
    ("pledging", "release", 45, r"(release|revocation|invocation).{0,30}(pledge|encumbr)"),
    ("pledging", "pledge", 74, r"pledge|encumbr|regulation 31\b|reg\.? ?31\b"),
    ("credit_rating", "downgrade", 86, r"(rating|outlook).{0,80}(downgrad|revised downward|negative)|downgrad"),
    ("credit_rating", "upgrade", 68, r"(rating|outlook).{0,80}(upgrad|positive)|upgrad"),
    ("credit_rating", "reaffirm", 22, r"(credit )?rating.{0,80}(reaffirm|re-affirm|assigned|affirm)"),
    ("credit_rating", "rating", 50, r"credit rating|\brating\b"),
    ("M&A", "housekeeping", 40, r"incorporation of .{0,40}subsidiar|investment in .{0,30}wholly.?owned"),
    ("M&A", "deal", 90, r"acqui|merger|amalgamat|de-?merger|scheme of arrangement|joint venture|slump sale|divest|stake|open offer|takeover|subsidiar"),
    ("management_change", "top", 86, r"(resign|appoint|cessation|retire|step.{0,6}down|demise|change).{0,120}(chief executive|chief financial|\bceo\b|\bcfo\b|managing director|\bmd\b|chairman|chairperson|whole.?time director|executive director)|(chief executive|chief financial|\bceo\b|\bcfo\b|managing director|chairman).{0,80}(resign|appoint|cessation|retire|step)"),
    ("management_change", "board", 42, r"independent director|additional director|non.?executive director|re-?appoint"),
    ("management_change", "change", 60, r"resign|appoint|cessation|retire|change in (director|key managerial|kmp|management|senior management)|key managerial"),
    ("fund_raise", "buyback", 82, r"buy-?back"),
    ("fund_raise", "equity", 80, r"\bqip\b|qualified institutional|preferential|rights issue|fund ?rais|raising of funds"),
    ("fund_raise", "debt", 38, r"debenture|\bncds?\b|commercial paper|\bbonds?\b|allotment of (securities|equity|shares)"),
    ("litigation", "action", 74, r"litigation|\bnclt\b|tribunal|penalt|show cause|demand (notice|order)|tax demand|sebi order|insolvency|arbitra|search and seizure|regulatory (order|action)|adjudicat|warning letter|\bfine\b|court|\bgst\b.{0,40}(order|notice|demand)|income tax.{0,40}(order|notice|demand)"),
    ("insider_trading", "sast", 48, r"regulation 29|reg\.? ?29\b|sast|takeover regulations"),
    ("insider_trading", "pit", 26, r"\(pit\)|insider|continual disclosure|form c\b"),
    ("bonus_split", "action", 62, r"bonus|stock split|sub-?division"),
    ("dividend", "dividend", 46, r"dividend"),
    ("capex", "capex", 70, r"capex|capacity (expansion|addition)|capital expenditure|new (plant|facility|unit)|greenfield|brownfield|commission(ing|ed)"),
    ("press_release", "order", 68, r"(receipt|award|bagged|secured|wins?|won).{0,40}(order|contract|project)|order (win|worth|valued)|letter of (award|intent|acceptance)"),
    ("press_release", "clarification", 62, r"clarification|rumou?r|news item"),
    ("press_release", "update", 44, r"press release|media release|launch|partnership|collaborat|monthly (business|sales)|business update|sales (volume|update)|production"),
]
_COMPILED = [(c, s, sc, re.compile(p, re.I | re.S)) for c, s, sc, p in RULES]


REFINE = {"credit_rating", "management_change", "press_release"}  # title names the topic, body carries the specifics


def classify(item):
    """Rule pass. The title decides the category (it is the most specific text); for a
    few categories the body then decides the sub-type (downgrade vs reaffirm, CFO vs director)."""
    title = item.get("title", "")
    full = " | ".join([title, item.get("exch_category", ""), item.get("body", "")])
    for text in (title, full):
        for cat, sub, score, rx in _COMPILED:
            if not rx.search(text):
                continue
            if cat == "investor_meetings" and re.search(r"transcript", full, re.I):
                return {"category": "earnings_call", "subtype": "transcript", "score": 30, "by": "rules"}
            if cat in REFINE:
                for c2, s2, sc2, rx2 in _COMPILED:
                    if c2 == cat and rx2.search(full):
                        return {"category": cat, "subtype": s2, "score": sc2, "by": "rules"}
            return {"category": cat, "subtype": sub, "score": score, "by": "rules"}
    return {"category": "unclassified", "subtype": "unknown", "score": 30, "by": "none"}


SYSTEM = ("You classify Indian stock-exchange filings for a portfolio manager. For each numbered filing return its "
          "category (one of: " + ", ".join(CATEGORIES) + ") and materiality 0-100, where 80+ could move the stock, "
          "40-70 is worth knowing, and under 30 is routine compliance. "
          'Reply as JSON: {"items":[{"n":1,"category":"...","materiality":55}]}')


def classify_many(items):
    """Classify a list; ambiguous ones go to the cheap model in a single batched call."""
    out, unknown = {}, []
    for it in items:
        hit, _ = cache.get("cls:" + it["id"])
        c = hit or classify(it)
        out[it["id"]] = c
        if c["by"] == "none":
            unknown.append(it)
    if unknown and llm.ready():
        for i in range(0, len(unknown), 25):
            batch = unknown[i:i + 25]
            listing = "\n".join(f"{n + 1}. [{b['symbol']}] {b['title']} :: {b.get('body', '')[:160]}"
                                for n, b in enumerate(batch))
            res = llm.chat_json("cheap", SYSTEM, listing, max_tokens=900) or {}
            for row in res.get("items", []) if isinstance(res, dict) else []:
                try:
                    it = batch[int(row["n"]) - 1]
                    cat = row["category"] if row.get("category") in CATEGORIES else "unclassified"
                    c = {"category": cat, "subtype": "model", "by": "model",
                         "score": max(0, min(100, int(row.get("materiality", 30))))}
                    out[it["id"]] = c
                    cache.put("cls:" + it["id"], c)
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
    return out
