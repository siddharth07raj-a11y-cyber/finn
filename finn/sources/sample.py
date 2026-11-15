"""A small FICTIONAL universe so FINN can be explored with no network and no API key.

Every company, person, filing and number here is invented. The UI shows a permanent
"Sample data" marker in this mode. The same engine code runs on it as on live data:
classification, scoring, alerts, analytics and the said-vs-did scorecard are all real.
"""
import random
from datetime import datetime, timedelta, date

from ..config import IST
from .announcements import _item, make_id

CO = {  # sym: name, sector, price, latest quarterly revenue (cr), growth recent/old %, opm, opm drift, fin, d/e, cash conv
    "TARANG":   ("Tarang Software Ltd", "IT services", 1840, 3150, 8, 18, 18.6, -1.1, False, 0.05, 0.95),
    "KAVERI":   ("Kaveri Cement Ltd", "Cement", 612, 4280, 15, 7, 19.4, 1.3, False, 0.55, 1.05),
    "NORBANK":  ("Northgate Bank Ltd", "Private bank", 428, 9100, 12, 14, 31.0, 0.2, True, 0.0, 1.0),
    "ZENPHAR":  ("Zenith Lifesciences Ltd", "Pharma", 1395, 2210, 13, 11, 24.2, 0.6, False, 0.18, 0.82),
    "LUMEN":    ("Lumen Electricals Ltd", "Capital goods", 5120, 1680, 22, 26, 13.1, 0.3, False, 0.12, 0.61),
    "SAHYAD":   ("Sahyadri Foods Ltd", "FMCG", 2260, 3900, 6, 9, 16.8, -0.4, False, 0.02, 1.1),
    "VAYU":     ("Vayu Aerospace Ltd", "Defence", 3980, 6400, 17, 12, 27.5, 0.9, False, 0.0, 1.2),
    "ORBITEL":  ("Orbit Telecom Ltd", "Telecom", 1120, 21500, 14, 16, 51.0, 1.0, False, 1.9, 1.3),
    "MERU":     ("Meru Motors Ltd", "Autos", 9850, 31200, 9, 13, 11.9, -0.2, False, 0.04, 0.98),
    "NILGIRI":  ("Nilgiri Retail Ltd", "Retail", 4310, 14800, 19, 24, 8.1, -0.1, False, 0.0, 0.7),
    "ARKA":     ("Arka Speciality Chemicals Ltd", "Chemicals", 2075, 1890, -4, 21, 14.9, -3.2, False, 0.31, 0.74),
    "DHRUV":    ("Dhruv Finance Ltd", "NBFC", 6890, 15400, 24, 27, 62.0, -0.5, True, 0.0, 1.0),
    "SETU":     ("Setu Infra Projects Ltd", "Infrastructure", 3420, 52000, 11, 15, 10.4, 0.1, False, 0.74, 0.88),
    "PRITHVI":  ("Prithvi Power Exchange Ltd", "Exchanges", 148, 152, 16, 12, 84.0, 0.0, False, 0.0, 1.02),
    "ASTERPIPE": ("Aster Pipes Ltd", "Building materials", 1505, 1420, 5, 18, 15.6, -1.4, False, 0.03, 0.9),
    # outside the portfolio - for ad-hoc research
    "HIMGIRI":  ("Himgiri Paints Ltd", "Paints", 2390, 8600, 3, 12, 17.2, -1.8, False, 0.06, 0.93),
    "SAGARPORT": ("Sagar Ports Ltd", "Logistics", 1310, 7900, 18, 13, 58.0, 0.7, False, 1.1, 1.15),
}
PORTFOLIO = list(CO)[:15]
RESEARCH_PICKS = ["HIMGIRI", "SAGARPORT"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def now():
    return datetime.now(IST)


def latest_q(today=None):
    """Most recent quarter end that is at least 30 days old (i.e. results are out)."""
    d = (today or now().date()) - timedelta(days=30)
    m = ((d.month - 1) // 3) * 3  # last completed quarter-end month, 0 -> previous Dec
    return (d.year - 1, 12) if m == 0 else (d.year, m)


def q_back(y, m, n):
    idx = y * 4 + m // 3 - 1 - n
    return idx // 4, (idx % 4 + 1) * 3


def qlabel(y, m):
    return f"{MON[m - 1]} {y}"


def fy_of(y, m):
    return y + 1 if m > 3 else y


def _quarters(sym, n=30):
    name, sector, price, rev_q, g_new, g_old, opm, drift, fin, de, conv = CO[sym]
    rnd = random.Random(sym)
    y, m = latest_q()
    out, rev = [], float(rev_q)
    for i in range(n):
        qy, qm = q_back(y, m, i)
        g = g_new if i < 5 else g_old
        margin = opm - drift * (i / 4) + rnd.uniform(-0.5, 0.5)
        sales = rev * (1 + rnd.uniform(-0.012, 0.012))
        op = sales * margin / 100
        oi, dep = sales * 0.014, sales * (0.0 if fin else 0.035)
        intr = sales * (0.0 if fin else 0.012 * de * 2)
        pbt = op + oi - intr - dep
        out.append({"y": qy, "m": qm, "sales": sales, "op": op, "oi": oi, "int": intr, "dep": dep,
                    "pbt": pbt, "np": pbt * 0.748})
        rev = rev / (1 + g / 100) ** 0.25
    return out[::-1]


def _tbl(cols, rows):
    return {"cols": cols, "rows": {k: [None if v is None else round(v, 2 if k == "eps" else 0) for v in vs]
                                   for k, vs in rows.items()}}


def company(sym):
    sym = sym.upper()
    if sym not in CO:
        raise ValueError(f"{sym} is not in the sample universe. Try: {', '.join(CO)}")
    name, sector, price, rev_q, g_new, g_old, opm, drift, fin, de, conv = CO[sym]
    qs = _quarters(sym)
    shares = max(rev_q * 4 * 3.2 / price, 1.0)  # crore shares, sized for a plausible market cap

    def prow(items):
        return {"sales": [q["sales"] for q in items],
                "expenses": [q["sales"] - q["op"] for q in items],
                "operating_profit": [q["op"] for q in items],
                "opm": [100 * q["op"] / q["sales"] for q in items],
                "other_income": [q["oi"] for q in items], "interest": [q["int"] for q in items],
                "depreciation": [q["dep"] for q in items], "pbt": [q["pbt"] for q in items],
                "tax_pct": [25 for _ in items], "net_profit": [q["np"] for q in items],
                "eps": [q["np"] / shares for q in items]}

    last13 = qs[-13:]
    quarters = _tbl([qlabel(q["y"], q["m"]) for q in last13], prow(last13))

    fys = {}
    for q in qs:
        fys.setdefault(fy_of(q["y"], q["m"]), []).append(q)
    full = [(fy, v) for fy, v in sorted(fys.items()) if len(v) == 4][-7:]
    agg = lambda v: {k: sum(q[k] for q in v) for k in ("sales", "op", "oi", "int", "dep", "pbt", "np")}  # noqa: E731
    years = [agg(v) for _, v in full] + [agg(qs[-4:])]
    pnl = _tbl([f"Mar {fy}" for fy, _ in full] + ["TTM"], prow(years))

    eq, bal_rows, cf_rows, rat_rows = years[0]["np"] * 5.5, {}, {}, {}
    rnd = random.Random(sym + "b")
    B = {k: [] for k in ("equity_capital", "reserves", "borrowings", "other_liabilities", "total_liabilities",
                         "fixed_assets", "cwip", "investments", "other_assets", "total_assets")}
    C = {k: [] for k in ("cfo", "cfi", "cff", "net_cash_flow", "fcf")}
    R = {k: [] for k in ("debtor_days", "inventory_days", "days_payable", "ccc", "working_capital_days", "roce", "roe")}
    for i, yv in enumerate(years[:-1]):
        eq += yv["np"] * 0.8
        debt = eq * de * (1 + 0.04 * (i - len(years) + 2))
        dep_liab = yv["sales"] * 6.5 if fin else 0
        other = yv["sales"] * 0.22
        tot = eq + debt + other + dep_liab
        fa = yv["sales"] * (0.02 if fin else 0.45)
        for k, v in (("equity_capital", shares * 2), ("reserves", eq - shares * 2), ("borrowings", debt),
                     ("other_liabilities", other), ("total_liabilities", tot), ("fixed_assets", fa),
                     ("cwip", fa * 0.08), ("investments", tot * 0.15), ("other_assets", tot - fa * 1.08 - tot * 0.15),
                     ("total_assets", tot)):
            B[k].append(v)
        if fin:
            B.setdefault("deposits", []).append(dep_liab)
        slip = (len(years) - 2 - i) * 0.03  # cash conversion drifts over time for low-conv names
        cfo = (yv["np"] + yv["dep"]) * (conv + (slip if conv < 0.9 else 0)) + rnd.uniform(-0.03, 0.03) * yv["np"]
        capex = yv["dep"] * 1.35 + yv["sales"] * 0.01
        C["cfo"].append(cfo); C["cfi"].append(-capex * 1.1); C["cff"].append(-(cfo - capex) * 0.7)
        C["net_cash_flow"].append(cfo - capex * 1.1 - (cfo - capex) * 0.7); C["fcf"].append(cfo - capex)
        dd = (38 if conv > 0.9 else 62) + (i * (0 if conv > 0.9 else 4))
        inv, pay = 41 + rnd.randint(-3, 3), 55 + rnd.randint(-3, 3)
        R["debtor_days"].append(dd); R["inventory_days"].append(inv); R["days_payable"].append(pay)
        R["ccc"].append(dd + inv - pay); R["working_capital_days"].append(dd + inv - pay - 12)
        R["roce"].append(100 * (yv["pbt"] + yv["int"]) / (eq + debt)); R["roe"].append(100 * yv["np"] / eq)
    ycols = [f"Mar {fy}" for fy, _ in full]
    ttm = years[-1]
    mcap = price * shares
    y, m = latest_q()
    calls = []
    if sym in TRANSCRIPTS:
        for i in range(5):
            qy, qm = q_back(y, m, i)
            cm = qm % 12 + 1
            calls.append({"date": f"{MON[cm - 1]} {qy + (1 if qm == 12 else 0)}",
                          "transcript": f"sample://{sym}/call/{i}", "ppt": None, "rec": None})
    return {
        "symbol": sym, "name": name, "sector": sector, "source": "sample data", "consolidated": True,
        "about": f"{name} is a fictional {sector.lower()} company used for FINN's offline sample mode.",
        "url": "", "bse_code": None, "nse_symbol": sym, "is_financial": fin,
        "ratios": {"market_cap": round(mcap), "current_price": price, "stock_p_e": round(mcap / ttm["np"], 1),
                   "roce": round(R["roce"][-1], 1), "roe": round(R["roe"][-1], 1),
                   "book_value": round(eq / shares), "dividend_yield": 0.8},
        "quarters": quarters, "pnl": pnl, "balance": _tbl(ycols, B), "cashflow": _tbl(ycols, C),
        "ratios_tbl": _tbl(ycols, R),
        "docs": {"annual_reports": [{"title": f"Financial Year {full[-1][0]}", "url": f"sample://{sym}/ar", "year": full[-1][0]}]
                 if sym in TRANSCRIPTS else [], "concalls": calls, "announcements": []},
    }


# ---- prices -----------------------------------------------------------------------
PLANTED = {"TARANG": (0, -6.4, 3.2), "LUMEN": (0, -1.3, 2.7), "KAVERI": (2, 4.8, 2.4), "ARKA": (1, -4.6, 1.4),
           "VAYU": (0, 2.1, 2.2), "ORBITEL": (6, 5.2, 1.8)}


def history(sym, rng="1y"):
    sym = sym.upper()
    if sym not in CO:
        raise ValueError(f"no sample prices for {sym}")
    rnd = random.Random(sym + "p")
    d, days = now().date(), []
    while len(days) < 250:  # the fictional exchange trades every day, so the demo is never "closed"
        days.append(d)
        d -= timedelta(days=1)
    price, base_vol = float(CO[sym][2]), int(4e9 / CO[sym][2] / 10)
    rows, back, pvol = [], PLANTED.get(sym), {}
    for i, day in enumerate(days):  # i = sessions back from latest
        chg, vx = rnd.gauss(0.04, 1.15), rnd.uniform(0.7, 1.35)
        if back and i == back[0]:
            chg, vx = back[1], back[2]
        pvol[i] = (chg, vx)
    c = price
    for i, day in enumerate(days):
        chg, vx = pvol[i]
        rows.append({"d": day.isoformat(), "o": round(c / (1 + chg / 200), 2), "h": round(c * 1.008, 2),
                     "l": round(c * 0.991, 2), "c": round(c, 2), "v": int(base_vol * vx)})
        c = c / (1 + chg / 100)
    return {"symbol": sym, "name": CO[sym][0], "currency": "INR", "rows": rows[::-1], "source": "sample data"}


# ---- filings ----------------------------------------------------------------------
def _fy_now():
    y, m = latest_q()
    return fy_of(y, m), {6: 1, 9: 2, 12: 3, 3: 4}[m]


FEED = [  # symbol, hours ago, title, body, exchange category, doc
    ("TARANG", 19, "Outcome of Board Meeting - Unaudited Financial Results for the quarter", "The Board approved the unaudited standalone and consolidated financial results. Full-year revenue growth guidance revised.", "Outcome of Board Meeting", None),
    ("TARANG", 19, "Press Release - Q{q} FY{fy} results", "Tarang Software reports quarterly results; deal wins TCV of USD 310 million.", "Press Release", None),
    ("TARANG", 18, "Investor Presentation", "Presentation to analysts on the quarterly results.", "Investor Presentation", None),
    ("LUMEN", 21, "Change in Directors / Key Managerial Personnel - Resignation of Chief Financial Officer and appointment of successor", "Mr. Rohan Kelkar has resigned as CFO to pursue other opportunities. The Board appointed Ms. Ananya Deshmukh as CFO and Key Managerial Personnel.", "Change in Director(s)", "lumen_cfo"),
    ("ZENPHAR", 9, "Acquisition - Agreement to acquire 74% stake in Medora Dermaceuticals Pvt Ltd", "Zenith Lifesciences will acquire 74% of Medora Dermaceuticals for Rs 1,180 crore in cash, funded from internal accruals; expected to close in 90 days.", "Acquisition", None),
    ("KAVERI", 44, "Credit Rating - Revision in rating outlook", "Rating on long-term bank facilities downgraded from AA+ to AA; outlook stable, citing debt-funded capacity expansion.", "Credit Rating", None),
    ("KAVERI", 52, "Outcome of Board Meeting - Approval of capacity expansion", "Board approved a 3.5 MTPA greenfield clinker and grinding unit at an estimated capex of Rs 2,950 crore, to be commissioned in 30 months.", "Outcome of Board Meeting", None),
    ("ARKA", 30, "Disclosure under Regulation 31 of SEBI (SAST) - Creation of pledge by promoter", "Promoter entity Arka Holdings has pledged 1.9 crore shares (4.6% of equity) in favour of a lender.", "Disclosure under SEBI Takeover Regulations", None),
    ("VAYU", 6, "Press Release - Receipt of order worth Rs 2,340 crore from the Ministry of Defence", "Vayu Aerospace has received an order valued at Rs 2,340 crore for avionics upgrade kits, to be executed over 36 months.", "Press Release", None),
    ("DHRUV", 14, "Allotment of Non-Convertible Debentures on private placement basis", "Allotted secured NCDs aggregating Rs 1,500 crore at a coupon of 8.05%.", "Allotment of Securities", None),
    ("SETU", 27, "Updates - Receipt of show cause notice from GST authority", "Received a show cause notice proposing a tax demand of Rs 86 crore plus interest; the company will contest.", "Updates", None),
    ("NORBANK", 70, "Board Meeting Intimation for considering fund raising", "Board to meet to consider raising equity capital up to Rs 5,000 crore through a Qualified Institutional Placement.", "Board Meeting Intimation", None),
    ("MERU", 3, "Monthly Business Update - Sales volumes", "Total sales of 1,82,400 units for the month, up 6% year on year; exports up 21%.", "Updates", None),
    ("ORBITEL", 150, "Dividend - Declaration of interim dividend and record date", "Interim dividend of Rs 4 per share; record date fixed.", "Dividend", None),
    ("NILGIRI", 100, "Bonus Issue - Board recommends bonus shares in the ratio 1:1", "Subject to shareholder approval; record date to be announced.", "Bonus", None),
    ("SAHYAD", 200, "Change in Directors - Appointment of Independent Director", "Appointed Dr. Meenal Joshi as an Additional (Independent) Director for five years.", "Change in Director(s)", None),
    ("PRITHVI", 300, "Updates - Regulatory order on market coupling", "The regulator issued directions on the phased implementation of market coupling in the day-ahead market.", "Updates", None),
    ("ASTERPIPE", 400, "Outcome of Board Meeting - Unaudited Financial Results for the quarter", "The Board approved the unaudited financial results.", "Outcome of Board Meeting", None),
    ("LUMEN", 20, "Analysts/Institutional Investor Meet - Schedule", "Schedule of meetings with institutional investors.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("TARANG", 15, "Copy of Newspaper Publication", "Newspaper advertisement of financial results.", "Copy of Newspaper Publication", None),
    ("TARANG", 10, "Earnings Call Transcript", "Transcript of the earnings conference call.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("NORBANK", 5, "ESOP/ESOS/ESPS - Allotment of equity shares under ESOP", "Allotment of 2,14,000 equity shares upon exercise of stock options.", "ESOP/ESOS/ESPS", None),
    ("NORBANK", 8, "Analysts/Institutional Investor Meet - Intimation", "Participation in an investor conference.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("SAHYAD", 12, "Loss/Duplicate-Share Certificate", "Intimation of loss of share certificates.", "Loss/Duplicate-Share Certificate", None),
    ("MERU", 16, "Trading Window", "Closure of trading window.", "Trading Window", None),
    ("ORBITEL", 11, "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Certificate under Regulation 74(5).", "Certificate under SEBI (Depositories and Participants) Regulations, 2018", None),
    ("NILGIRI", 13, "Analysts/Institutional Investor Meet - Intimation", "Meeting with a mutual fund.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("SETU", 17, "Shareholders meeting - Notice of Postal Ballot", "Postal ballot notice for re-appointment of a director.", "Shareholders meeting", None),
    ("PRITHVI", 22, "Business Responsibility and Sustainability Reporting (BRSR)", "Submission of BRSR.", "Updates", None),
    ("DHRUV", 23, "Analysts/Institutional Investor Meet - Intimation", "Non-deal roadshow schedule.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("ZENPHAR", 20, "Copy of Newspaper Publication", "Notice to shareholders regarding transfer of shares to IEPF.", "Copy of Newspaper Publication", None),
    ("VAYU", 2, "Disclosure under SEBI (PIT) Regulations - Continual disclosure", "A designated person sold 1,200 shares in the open market.", "Disclosure under SEBI (PIT) Regulations", None),
    ("ASTERPIPE", 7, "ESOP/ESOS/ESPS - Grant of options", "Grant of 40,000 stock options to employees.", "ESOP/ESOS/ESPS", None),
    ("KAVERI", 60, "Analysts/Institutional Investor Meet - Intimation", "Plant visit by analysts.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
    ("ARKA", 80, "Shareholders meeting - Proceedings of AGM", "Summary of proceedings of the Annual General Meeting.", "Shareholders meeting", None),
    ("MERU", 120, "Trading Window", "Closure of trading window.", "Trading Window", None),
    ("SAHYAD", 130, "Appointment of Secretarial Auditor", "Appointment of secretarial auditor for five years.", "Updates", None),
    ("ORBITEL", 160, "Analysts/Institutional Investor Meet - Intimation", "Investor conference participation.", "Analysts/Institutional Investor Meet/Con. Call Updates", None),
]

DOC_TEXT = {
    "lumen_cfo": ["""Sub: Intimation under Regulation 30 - Change in Key Managerial Personnel
We wish to inform you that Mr. Rohan Kelkar has tendered his resignation as Chief Financial Officer of the Company with effect from close of business hours, to pursue opportunities outside the Company. He has confirmed there are no other material reasons for his resignation.
The Board of Directors, on the recommendation of the Nomination and Remuneration Committee, has approved the appointment of Ms. Ananya Deshmukh as Chief Financial Officer and Key Managerial Personnel of the Company.
Brief Profile: Ms. Ananya Deshmukh is a Chartered Accountant with over 22 years of experience in corporate finance, treasury and investor relations. She was most recently Deputy CFO at Varuna Industrial Systems Ltd, where she led a Rs 2,400 crore refinancing and the listing of its components subsidiary. Earlier she spent 11 years at Corbel Engineering in finance controllership roles. She holds a B.Com from the University of Pune.
Disclosure of relationships between directors: Not applicable."""],
}


def announcements(sym, start, end, **_):
    sym = sym.upper()
    fy, q = _fy_now()
    out, t = [], now()
    for s, hrs, title, body, cat, doc in FEED:
        if s != sym:
            continue
        dt = t - timedelta(hours=hrs, minutes=(len(title) * 7) % 50)
        if not (start <= dt.date() <= end):
            continue
        title = title.format(q=q, fy=fy % 100)
        it = _item(sym, CO[sym][0], dt, title, body, f"sample://doc/{doc}" if doc else "", cat, "sample data")
        it["id"] = make_id(sym, "sample", title)  # stable across refreshes
        out.append(it)
    return out


def _call(sym, i):
    """Transcript i quarters back, written against the generated fiscal calendar."""
    y, m = latest_q()
    qy, qm = q_back(y, m, i)
    fy = fy_of(qy, qm)
    qn = {6: 1, 9: 2, 12: 3, 3: 4}[qm]
    # At the Q4 call management guides for the year that has just begun.
    ctx = {"fy": (fy + 1 if qn == 4 else fy) % 100, "pfy": fy % 100, "q": qn, "co": CO[sym][0]}
    return [p.format(**ctx) for p in TRANSCRIPTS[sym][i]]


def doc_pages(url):
    parts = url.replace("sample://", "").split("/")
    if parts[0] == "doc":
        return DOC_TEXT.get(parts[1], [])
    sym = parts[0]
    if parts[1] == "call":
        return _call(sym, int(parts[2]))
    if parts[1] == "ar":
        return AR.get(sym, [])
    return []


def search(q):
    q = q.lower()
    return [{"symbol": s, "name": v[0]} for s, v in CO.items() if q in s.lower() or q in v[0].lower()]


OPEN = "{co} Q{q} FY{pfy} Earnings Conference Call\nManagement: Managing Director & CEO; Chief Financial Officer\nModerator: Ladies and gentlemen, good day and welcome to the earnings conference call."
TRANSCRIPTS = {
    "TARANG": [  # index 0 = latest call
        [OPEN, "CEO: This was a softer quarter than we had planned for. Two large banking clients deferred programmes and discretionary spending in retail remained weak. Our deal pipeline is the strongest it has ever been and we remain very excited about our AI-led offerings.\nGiven the first-half performance, we now expect revenue growth of 9% to 10% for FY{fy}. We expect EBITDA margin of 18% to 19% for FY{fy}, as wage hikes were rolled out this quarter.",
         "Analyst: You started the year at 13% to 15%. What changed?\nCFO: Ramp-ups in two large deals moved to the second half. We have not lost any client. Capex for FY{fy} will be around Rs 220 crore, largely for the new campus."],
        [OPEN, "CEO: We had a steady start to the year with broad-based growth. Demand environment is improving and conversations with clients are very encouraging.\nWe reiterate our guidance of revenue growth of 13% to 15% for FY{fy}. We are confident of maintaining EBITDA margin in the range of 19% to 20% for FY{fy}.",
         "Analyst: First-quarter growth looks below the guided band.\nCFO: Growth will be back-ended this year. We have good visibility for the second half."],
        [OPEN, "CEO: We closed the year with record deal wins. We enter the new year with strong momentum and the best order book in our history.\nFor FY{fy}, we are guiding for revenue growth of 13% to 15%. We expect EBITDA margin in the range of 19% to 20% for FY{fy}. We plan capex of Rs 250 crore in FY{fy}.",
         "Analyst: FY{pfy} growth came in below what you guided at the start of last year.\nCEO: That was largely due to one client insourcing work. That is behind us."],
        [OPEN, "CEO: The quarter was impacted by furloughs, which were higher than usual. Client budgets for the new calendar year look healthy.\nWe now expect revenue growth of 11% to 12% for FY{fy}. EBITDA margin for FY{fy} should be around 20%.",
         "Analyst: Is the margin guidance of 20% to 21% still valid?\nCFO: We will be at the lower end, around 20%, given investments in sales."],
        [OPEN, "CEO: We delivered a good quarter and the outlook remains robust across verticals.\nWe are confident of delivering revenue growth of 15% to 17% in FY{fy}. We expect EBITDA margin of 20% to 21% for FY{fy}.",
         "Analyst: What gives you confidence on the top end?\nCEO: Large deal ramp-ups and a healthy pipeline in BFSI."],
    ],
    "KAVERI": [
        [OPEN, "MD: Demand in our core southern and eastern markets stayed strong, led by housing and infrastructure. Realisations improved by 3% sequentially.\nWe expect volume-led revenue growth of 13% to 15% in FY{fy}. We expect EBITDA margin of 19% to 20% for FY{fy} as fuel costs remain benign.\nNet debt will rise as we fund the new clinker line; we expect capex of Rs 1,100 crore in FY{fy}.",
         "Analyst: The rating agency flagged leverage.\nCFO: Net debt to EBITDA will peak below 2.5 times and come down once the new line is commissioned."],
        [OPEN, "MD: A good start to the year despite an early monsoon.\nWe maintain our guidance of revenue growth of 12% to 14% for FY{fy}. EBITDA margin for FY{fy} should be in the range of 18% to 19%.", "Analyst: Any change in the expansion timeline?\nMD: No change."],
        [OPEN, "MD: We ended the year with our highest ever quarterly volumes.\nFor FY{fy}, we are guiding for revenue growth of 12% to 14%. We expect EBITDA margin of 18% to 19% for FY{fy}.", "Analyst: Pricing outlook?\nMD: We expect prices to hold."],
        [OPEN, "MD: Volumes grew in double digits.\nWe expect revenue growth of 9% to 11% for FY{fy}. EBITDA margin for FY{fy} should be 17% to 18%.", "Analyst: Fuel mix?\nCFO: Petcoke share is now 55%."],
        [OPEN, "MD: Demand recovery is under way after a weak first half.\nWe expect revenue growth of 8% to 10% in FY{fy}. We expect EBITDA margin of 17% to 18% for FY{fy}.", "Analyst: Capex plans?\nMD: We will finalise the next phase shortly."],
    ],
}
AR = {
    "TARANG": ["Management Discussion and Analysis\nTarang Software is a fictional IT services company. Revenue mix by vertical: Banking and financial services 41%, Retail and consumer 22%, Manufacturing 19%, Healthcare 11%, Others 7%. By geography: North America 62%, Europe 24%, Rest of World 14%. The top ten clients contributed 38% of revenue. Headcount was 24,300 with attrition of 13.1%."],
    "KAVERI": ["Management Discussion and Analysis\nKaveri Cement is a fictional cement manufacturer with installed capacity of 18.5 MTPA across four integrated plants and two grinding units. Sales mix: trade 68%, non-trade 32%. Region mix: South 57%, East 31%, West 12%. Blended cement formed 71% of volumes. Power and fuel was 29% of operating cost."],
}
