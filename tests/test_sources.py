"""Parsers for each upstream format, against fixtures in the shape the sources return."""
from datetime import datetime
from pathlib import Path

from finn import analytics
from finn.config import IST
import importlib

A = importlib.import_module("finn.sources.announcements")
P = importlib.import_module("finn.sources.prices")
S = importlib.import_module("finn.sources.screener")
from finn.sources.documents import _candidates

FIX = Path(__file__).parent / "fixtures"


def test_screener_company_page():
    c = S.parse_company((FIX / "screener_reliance.html").read_text(), "reliance")
    assert c["name"] == "Reliance Industries Ltd" and c["bse_code"] == "500325" and c["nse_symbol"] == "RELIANCE"
    assert c["ratios"]["market_cap"] == 1812954 and c["ratios"]["roe"] == 8.91
    q = c["quarters"]
    assert q["cols"][-1] == "Sep 2026" and q["rows"]["sales"][-1] == 330601 and q["rows"]["opm"][-1] == 17
    assert "raw_pdf" not in q["rows"] and not c["is_financial"]
    assert c["pnl"]["cols"][-1] == "TTM" and c["balance"]["rows"]["borrowings"][-1] == 405322
    assert c["cashflow"]["rows"]["cfo"][-1] == 192113 and c["ratios"]["roce"] == 10.3 and c["ratios_tbl"]["rows"]["ccc"] == [-3, -8, 25]
    d = c["docs"]
    assert [a["year"] for a in d["annual_reports"]] == [2026, 2025] and d["annual_reports"][0]["title"] == "Financial Year 2026"
    assert d["concalls"][0]["date"] == "Nov 2026" and d["concalls"][0]["transcript"].endswith("cf020fb9c816.pdf")
    assert d["concalls"][0]["rec"].startswith("https://www.youtube.com") and d["concalls"][2]["transcript"] is None
    assert d["announcements"][0]["title"].endswith("Credit Rating") and d["announcements"][0]["sub"].startswith("4 Nov")


def test_headline_first_cut_from_real_numbers():
    c = S.parse_company((FIX / "screener_reliance.html").read_text(), "RELIANCE")
    c["consolidated"] = True
    h = analytics.headline(c)
    rows = {r["label"]: r for r in h["rows"]}
    assert h["quarter"] == "Sep 2026" and h["year_ago"] == "Sep 2025"
    assert rows["Revenue"]["value"] == 330601 and rows["Revenue"]["qoq"] == 6.8 and rows["Revenue"]["yoy"] == 29.8
    assert rows["EBITDA"]["yoy"] == 23.4 and rows["PBT"]["qoq"] == 26.1 and rows["PAT"]["yoy"] == 33.8


def test_nse_and_bse_rows_normalise_to_one_shape():
    nse = A.parse_nse([{"symbol": "INFY", "desc": "Change in Director(s)", "attchmntText": "Infosys has informed the Exchange regarding appointment of CFO",
                        "attchmntFile": "https://nsearchives.nseindia.com/corporate/x.pdf", "sm_name": "Infosys Limited",
                        "an_dt": "14-Nov-2026 18:02:11", "sort_date": "2026-11-14 18:02:11"}, {"desc": "bad", "sort_date": "?"}], "INFY")
    assert len(nse) == 1 and nse[0]["dt"].startswith("2026-11-14T18:02:11") and nse[0]["source"] == "NSE"
    assert nse[0]["title"] == "Change in Director(s)" and nse[0].pop("headline") == "Appointment of CFO"
    bse = A.parse_bse({"Table": [{"NEWSSUB": "Infosys Ltd - 500209 - Board Meeting Outcome for Financial Results", "HEADLINE": "Results approved",
                                  "CATEGORYNAME": "Result", "SUBCATNAME": "Financial Results", "DT_TM": "2026-11-14T18:22:31.56",
                                  "ATTACHMENTNAME": "abc.pdf", "SLONGNAME": "Infosys Ltd"}]}, "INFY")
    assert bse[0]["title"] == "Board Meeting Outcome for Financial Results" and bse[0]["url"].endswith("AttachLive/abc.pdf")
    assert set(nse[0]) == set(bse[0])


def test_screener_relative_dates():
    now = datetime(2026, 11, 15, 12, tzinfo=IST)
    assert A.parse_screener_date("2d - x", now).day == 13
    assert A.parse_screener_date("4 Nov - y", now).isoformat().startswith("2026-11-04")
    assert A.parse_screener_date("28 Dec - z", now).year == 2025


def test_yahoo_chart_payload():
    payload = {"chart": {"result": [{"meta": {"currency": "INR", "gmtoffset": 19800, "longName": "Reliance Industries Limited"},
               "timestamp": [1794627900, 1794714300, 1794800700],
               "indicators": {"quote": [{"open": [1330.0, 1338.5, None], "high": [1345, 1350, None], "low": [1325, 1331, None],
                                         "close": [1338.25, 1340.1, None], "volume": [9000000, 21000000, None]}]}}], "error": None}}
    px = P.parse_chart(payload, "RELIANCE")
    assert len(px["rows"]) == 2 and px["rows"][-1]["c"] == 1340.1 and px["rows"][-1]["v"] == 21000000
    assert px["rows"][0]["d"] < px["rows"][1]["d"]


def test_bse_attachment_url_fallbacks():
    c = _candidates("https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=8e997741-4d35.pdf")
    assert any("AttachLive/8e997741-4d35.pdf" in u for u in c) and any("AttachHis" in u for u in c)


def test_filing_sources_fall_back_in_order(monkeypatch):
    from datetime import date
    calls = []

    def nse(*a, **k):
        calls.append("nse"); raise RuntimeError("403")

    def bse(symbol, start, end, bse_code=None, **k):
        calls.append(("bse", bse_code))
        return A.parse_bse({"Table": [{"NEWSSUB": "Board Meeting Outcome", "DT_TM": "2026-11-14T18:22:31", "ATTACHMENTNAME": "a.pdf"}]}, symbol)

    monkeypatch.setitem(A.SOURCES, "nse", nse)
    monkeypatch.setitem(A.SOURCES, "bse", bse)
    got = A.fetch("INFY", date(2026, 11, 1), date(2026, 11, 15), resolve=lambda: {"bse_code": "500209"})
    assert calls == ["nse", ("bse", "500209")] and len(got) == 1 and got[0]["source"] == "BSE"
