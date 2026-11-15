"""Company fundamentals + primary-document links from screener.in.

One page per company gives: standardised quarterly / annual P&L, balance sheet, cash
flow, ratios, and links to the annual reports and concall transcripts (hosted on BSE
or the company's IR site). Works for any listed ticker - nothing is hard-wired.
"""
import re

from bs4 import BeautifulSoup

from .. import http

BASE = "https://www.screener.in"

LABELS = {
    "sales": "sales", "revenue": "sales", "expenses": "expenses",
    "operating profit": "operating_profit", "financing profit": "operating_profit",
    "opm": "opm", "financing margin": "opm", "other income": "other_income",
    "interest": "interest", "depreciation": "depreciation", "profit before tax": "pbt",
    "tax": "tax_pct", "net profit": "net_profit", "eps in rs": "eps",
    "dividend payout": "dividend_payout", "equity capital": "equity_capital",
    "reserves": "reserves", "borrowings": "borrowings", "borrowing": "borrowings",
    "deposits": "deposits", "other liabilities": "other_liabilities",
    "total liabilities": "total_liabilities", "fixed assets": "fixed_assets", "cwip": "cwip",
    "investments": "investments", "other assets": "other_assets", "total assets": "total_assets",
    "cash from operating activity": "cfo", "cash from investing activity": "cfi",
    "cash from financing activity": "cff", "net cash flow": "net_cash_flow",
    "free cash flow": "fcf", "cfo/ebitda": "cfo_ebitda", "debtor days": "debtor_days",
    "inventory days": "inventory_days", "days payable": "days_payable",
    "cash conversion cycle": "ccc", "working capital days": "working_capital_days",
    "roce": "roce", "roe": "roe", "gross npa": "gross_npa", "net npa": "net_npa",
}
SECTIONS = {"quarters": "quarters", "profit-loss": "pnl", "balance-sheet": "balance",
            "cash-flow": "cashflow", "ratios": "ratios_tbl"}


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _key(label):
    k = _clean(label).lower().replace("+", "").replace("%", "").strip()
    return LABELS.get(k) or re.sub(r"[^a-z0-9]+", "_", k).strip("_")


def num(s):
    s = _clean(s).replace(",", "").replace("%", "").replace("₹", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _table(section):
    t = section.find("table") if section else None
    if not t:
        return {"cols": [], "rows": {}}
    head = t.find("thead") or t
    cols = [_clean(th.get_text()) for th in head.find_all("th")][1:]
    rows = {}
    for tr in (t.find("tbody") or t).find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        key = _key(tds[0].get_text())
        if not key or key == "raw_pdf":
            continue
        vals = [num(td.get_text()) for td in tds[1:]]
        rows[key] = (vals + [None] * len(cols))[:len(cols)]
    return {"cols": cols, "rows": rows}


def _doc_list(docs, heading):
    """Find the heading inside #documents and return the <li> items of its list.
    Walks up from the heading until a container with list items is found, so an extra
    wrapper <div> around the heading does not break it."""
    if not docs:
        return []
    for h in docs.find_all(["h3", "h2", "h4"]):
        if not _clean(h.get_text()).lower().startswith(heading):
            continue
        box = h.parent
        while box is not None and box is not docs:
            items = box.find_all("li")
            if items:
                return items
            box = box.parent
    return []


def parse_company(html, symbol):
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if not h1:
        raise ValueError(f"screener: no company page for {symbol}")
    out = {"symbol": symbol.upper(), "name": _clean(h1.get_text()), "source": "screener.in"}

    about = soup.select_one(".company-profile .about") or soup.select_one(".about")
    out["about"] = _clean(about.get_text()) if about else ""

    ratios = {}
    for li in soup.select("#top-ratios li"):
        n, v = li.select_one(".name"), li.select_one(".number")
        if n and v:
            ratios[_key(n.get_text())] = num(v.get_text())
    out["ratios"] = ratios

    out["bse_code"] = out["nse_symbol"] = None
    for a in soup.find_all("a", href=True):
        m = re.search(r"bseindia\.com/stock-share-price/.*?/(\d{6})/?", a["href"])
        if m and not out["bse_code"]:
            out["bse_code"] = m.group(1)
        m = re.search(r"nseindia\.com/get-quotes/equity\?symbol=([A-Z0-9&\-]+)", a["href"])
        if m and not out["nse_symbol"]:
            out["nse_symbol"] = m.group(1)

    for sec_id, name in SECTIONS.items():
        out[name] = _table(soup.find(id=sec_id))
    out["is_financial"] = "Financing Profit" in html or "deposits" in out["balance"]["rows"]

    docs = soup.find(id="documents")
    ars = []
    for li in _doc_list(docs, "annual report"):
        a = li.find("a", href=True)
        if not a:
            continue
        t = _clean(a.get_text())
        y = re.search(r"(20\d\d)", t)
        ars.append({"title": re.sub(r"\s*from (bse|nse)$", "", t, flags=re.I), "url": a["href"],
                    "year": int(y.group(1)) if y else None})
    calls = []
    for li in _doc_list(docs, "concall"):
        text = _clean(li.get_text(" "))
        m = re.match(r"([A-Z][a-z]{2} \d{4})", text)
        if not m:
            continue
        c = {"date": m.group(1), "transcript": None, "ppt": None, "rec": None}
        for a in li.find_all("a", href=True):
            lab = _clean(a.get_text()).lower()
            if lab.startswith("transcript"):
                c["transcript"] = a["href"]
            elif lab.startswith("ppt"):
                c["ppt"] = a["href"]
            elif lab.startswith("rec"):
                c["rec"] = a["href"]
        calls.append(c)
    anns = []
    for li in _doc_list(docs, "announcement"):
        a = li.find("a", href=True)
        if not a:
            continue
        sub = a.find("div")
        sub_t = _clean(sub.get_text()) if sub else ""
        if sub:
            sub.extract()
        anns.append({"title": _clean(a.get_text()), "sub": sub_t, "url": a["href"]})
    out["docs"] = {"annual_reports": ars, "concalls": calls, "announcements": anns}
    return out


def company(symbol):
    """Consolidated numbers when the company reports them, standalone otherwise."""
    symbol = symbol.upper().strip()
    last = None
    for path in (f"/company/{symbol}/consolidated/", f"/company/{symbol}/"):
        try:
            r = http.get(BASE + path, timeout=20, retries=1)
            c = parse_company(r.text, symbol)
            if c["quarters"]["rows"].get("sales") and any(v is not None for v in c["quarters"]["rows"]["sales"]):
                c["consolidated"] = "consolidated" in path
                c["url"] = BASE + path
                return c
            last = ValueError(f"screener: no financials for {symbol}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def search(q):
    r = http.get(BASE + "/api/company/search/", params={"q": q}, timeout=10)
    out = []
    for it in r.json():
        m = re.search(r"/company/([^/]+)/", it.get("url", ""))
        if m:
            out.append({"symbol": m.group(1).upper(), "name": it.get("name", "")})
    return out
