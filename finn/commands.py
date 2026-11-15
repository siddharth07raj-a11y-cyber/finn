"""One input box, many intents. Rules resolve it; nothing here needs a model.

  "TCS"                              -> open research
  "what changed this week"           -> re-window the brief
  "alert me if volume is over 3x"    -> change a rule
  "what did INFY say about margins"  -> grounded Q&A on that company
"""
import re

from . import sources

NOT_TICKERS = {"WHAT", "SHOW", "TELL", "THE", "AND", "FOR", "LAST", "WEEK", "DAYS", "DAY", "ALERT", "WHEN", "OVER", "HOW",
               "DID", "SAY", "ABOUT", "PRICE", "VOLUME", "TODAY", "RESULTS", "CAPEX", "MARGIN", "MARGINS", "DEBT", "WHY",
               "IS", "ARE", "ME", "IF", "ON", "IN", "OF", "TO", "MY", "ANY", "NEW", "CEO", "CFO", "FY", "QOQ", "YOY", "PAT", "PBT", "EBITDA"}


def _symbol(text, context=None):
    known = set(sources.portfolio()) | set(sources.research_picks())
    words = re.findall(r"[A-Za-z&\-]{2,15}", text)
    for w in words:
        if w.upper() in known:
            return w.upper()
    for w in words:  # an ALL-CAPS token typed by the user is treated as a ticker
        if w.isupper() and w not in NOT_TICKERS and len(w) >= 3:
            return w
    if len(words) <= 3 and not re.search(r"\d", text):
        try:
            hits = sources.search(text.strip())
            if hits:
                return hits[0]["symbol"]
        except Exception:  # noqa: BLE001
            pass
        if len(words) == 1 and words[0].upper() not in NOT_TICKERS:
            return words[0].upper()
    return context


def parse(text, context=None):
    t = text.strip()
    lo = t.lower()
    if not t:
        return {"intent": "none"}
    # rules
    patch = {}
    if re.search(r"alert|notify|tell me|flag|watch|threshold|unusual", lo) or re.search(r"\d\s*(x|×|%)", lo):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|×|times)", lo)
        if m and re.search(r"vol", lo):
            patch["vol"] = float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", lo)
        if m and re.search(r"price|move|moves|fall|drop|rise|up|down|swing", lo):
            patch["px"] = float(m.group(1))
        m = re.search(r"(\d+)[ -]?(?:day|session)s? (?:average|avg|lookback)", lo)
        if m:
            patch["lookback"] = int(m.group(1))
    if patch:
        said = []
        if "vol" in patch:
            said.append(f"volume at {patch['vol']:g}× its average")
        if "px" in patch:
            said.append(f"a price move of ±{patch['px']:g}%")
        if "lookback" in patch:
            said.append(f"a {patch['lookback']}-session average")
        return {"intent": "rule", "patch": patch, "say": "Watching for " + " and ".join(said) + "."}
    # window
    m = re.search(r"(?:last|past)\s+(\d+)\s*(h|hour|d|day|w|week|month)", lo)
    win = None
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        hours = n * {"h": 1, "d": 24, "w": 168, "m": 720}[u]
        win = "24h" if hours <= 24 else "3d" if hours <= 72 else "7d" if hours <= 168 else "30d"
    elif re.search(r"\btoday\b|what changed$|what's new|whats new|my brief|the brief", lo):
        win = "24h"
    elif re.search(r"this week|past week|last week", lo):
        win = "7d"
    elif re.search(r"this month|past month|last month", lo):
        win = "30d"
    sym = _symbol(t, context)
    if win and not (sym and sym != context):
        return {"intent": "digest", "window": win}
    if sym:
        is_q = len(t.split()) > 3 or "?" in t
        if is_q:
            return {"intent": "ask", "symbol": sym, "question": t}
        return {"intent": "research", "symbol": sym}
    return {"intent": "unknown", "say": "Type a ticker (TCS), a question about a company, a time window (last 7 days) or a rule (alert me if volume is over 3x)."}
