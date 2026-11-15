"""Corporate announcements for a symbol, normalised to one shape.

Chain: NSE API -> BSE API -> screener.in's recent-announcements list. The exchanges
throttle datacentre IPs unpredictably, so each source is tried in order and the first
that answers wins.
"""
import hashlib
import re
import threading
from datetime import datetime, timedelta

from .. import http
from ..config import IST, ANN_ORDER

_nse = {"session": None, "t": 0.0}
_nse_lock = threading.Lock()


def make_id(symbol, dt, title):
    return hashlib.sha1(f"{symbol}|{dt}|{title}".encode()).hexdigest()[:12]


def _item(symbol, company, dt, title, body, url, exch_cat, source):
    title = re.sub(r"\s+", " ", title or "").strip()
    body = re.sub(r"\s+", " ", body or "").strip()
    return {"id": make_id(symbol, dt.isoformat(), title), "symbol": symbol, "company": company or symbol,
            "dt": dt.isoformat(), "title": title, "body": body, "url": url or "",
            "exch_category": exch_cat or "", "source": source}


# ---- NSE --------------------------------------------------------------------------
def _nse_session():
    import time
    with _nse_lock:
        if _nse["session"] is None or time.time() - _nse["t"] > 600:
            s = http.new_session()
            s.headers.update({"Accept": "application/json, text/plain, */*",
                              "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"})
            s.get("https://www.nseindia.com", timeout=12)  # sets the cookies the API requires
            _nse.update(session=s, t=time.time())
        return _nse["session"]


def parse_nse(rows, symbol):
    out = []
    for r in rows or []:
        raw = r.get("sort_date") or r.get("an_dt") or ""
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt).replace(tzinfo=IST)
                break
            except ValueError:
                pass
        if not dt:
            continue
        it = _item(symbol, r.get("sm_name"), dt, r.get("desc"), r.get("attchmntText"),
                   r.get("attchmntFile"), r.get("desc"), "NSE")
        # NSE's subject is a generic category ("Updates"); the specifics are in the text.
        text = re.sub(r"^.{0,80}? has (?:informed|submitted to) the Exchange,?\s*(?:regarding|about|a copy of|that)?\s*(?:the\s+)?", "", it["body"], flags=re.I)
        text = re.sub(r"\b(Mr|Ms|Mrs|Dr|Smt|Prof|M/s|Rs|No)\.", r"\1", text)  # these dots do not end the sentence
        text = re.split(r"(?<=[.;])\s", text.strip(" '\""))[0].rstrip(".")
        if len(text) >= 12 and (len(text) > len(it["title"]) + 15 or not text.lower().startswith(it["title"].lower()[:18])):
            it["headline"] = (text[0].upper() + text[1:])[:150]
        out.append(it)
    return out


def from_nse(symbol, start, end, **_):
    try:
        s = _nse_session()
        r = http.get("https://www.nseindia.com/api/corporate-announcements",
                     params={"index": "equities", "symbol": symbol,
                             "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")},
                     session=s, timeout=15)
        return parse_nse(r.json(), symbol)
    except Exception:
        _nse["session"] = None  # force a cookie refresh next time
        raise


# ---- BSE --------------------------------------------------------------------------
def parse_bse(payload, symbol):
    out = []
    for r in (payload or {}).get("Table") or []:
        raw = (r.get("DT_TM") or r.get("NEWS_DT") or "")[:19]
        try:
            dt = datetime.fromisoformat(raw).replace(tzinfo=IST)
        except ValueError:
            continue
        att = r.get("ATTACHMENTNAME") or ""
        url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else (r.get("NSURL") or "")
        cat = " / ".join(x for x in (r.get("CATEGORYNAME"), r.get("SUBCATNAME")) if x)
        title = r.get("NEWSSUB") or r.get("HEADLINE") or ""
        title = re.sub(r"^.*? - \d{6} - ", "", title)  # drop "Company - 500325 - " prefix
        out.append(_item(symbol, r.get("SLONGNAME"), dt, title, r.get("HEADLINE") or r.get("MORE"), url, cat, "BSE"))
    return out


def from_bse(symbol, start, end, bse_code=None, **_):
    if not bse_code:
        raise ValueError("BSE scrip code unknown")
    headers = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
               "Accept": "application/json, text/plain, */*"}
    # Public references disagree on the date format this endpoint expects, so try both.
    for fmt in ("%Y%m%d", "%d%m%Y"):
        out = []
        for page in (1, 2, 3):
            r = http.get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                         params={"pageno": page, "strCat": "-1", "strPrevDate": start.strftime(fmt),
                                 "strScrip": bse_code, "strSearch": "P", "strToDate": end.strftime(fmt),
                                 "strType": "C", "subcategory": "-1"}, headers=headers, timeout=15)
            got = parse_bse(r.json(), symbol)
            out += got
            if len(got) < 50:
                break
        if out:
            return out
    return []


# ---- screener.in (last resort: only the most recent handful) --------------------------
def parse_screener_date(sub, now):
    m = re.match(r"(\d+)\s*([hdm])\b", sub)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return now - (timedelta(hours=n) if u == "h" else timedelta(days=n) if u == "d" else timedelta(minutes=n))
    m = re.match(r"(\d{1,2}) ([A-Z][a-z]{2})(?: (\d{4}))?", sub)
    if m:
        y = int(m.group(3) or now.year)
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {y}", "%d %b %Y").replace(tzinfo=IST, hour=12)
        except ValueError:
            return None
        return dt.replace(year=y - 1) if dt > now + timedelta(days=2) and not m.group(3) else dt
    return None


def from_screener(symbol, start, end, company=None, **_):
    if not company:
        raise ValueError("no screener page")
    now = datetime.now(IST)
    out = []
    for a in company["docs"]["announcements"]:
        dt = parse_screener_date(a["sub"], now)
        if not dt:
            continue
        body = re.sub(r"^[^-]*-\s*", "", a["sub"])
        out.append(_item(symbol, company["name"], dt, a["title"], body, a["url"], "", "BSE via screener.in"))
    return out


SOURCES = {"nse": from_nse, "bse": from_bse, "screener": from_screener}


def fetch(symbol, start, end, resolve=None):
    """`resolve` returns the company's screener record (BSE code, recent filings). It is
    only called if NSE fails, so the common path costs one request per symbol."""
    errors, co = [], None
    for name in ANN_ORDER:
        try:
            if name in ("bse", "screener") and co is None and resolve:
                co = resolve() or {}
            items = SOURCES[name](symbol, start, end, bse_code=(co or {}).get("bse_code"), company=co or None)
            lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
            return [i for i in items if lo <= i["dt"] <= hi]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {str(e)[:80]}")
    raise RuntimeError("; ".join(errors))
