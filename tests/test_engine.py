"""Classification, alerts, said-vs-did, the model router and the HTTP API."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from finn import classify, commands, config, guidance, llm, moves, sources
from finn.app import app

CASES = [
    ("Outcome of Board Meeting - Unaudited Financial Results for the quarter ended September 30, 2026", "", "results", "filing"),
    ("Board Meeting Intimation for considering financial results", "", "results", "upcoming"),
    ("Copy of Newspaper Publication", "Financial results published", "unclassified", "routine"),
    ("Change in Director(s)", "resignation of Mr. X as Chief Financial Officer", "management_change", "top"),
    ("Change in Director(s)", "appointment of Ms. Y as Independent Director", "management_change", "board"),
    ("Credit Rating", "CRISIL has reaffirmed the rating at AAA/Stable", "credit_rating", "reaffirm"),
    ("Credit Rating", "ICRA has downgraded the long-term rating to AA-", "credit_rating", "downgrade"),
    ("Acquisition", "acquired 100% stake in ABC Pvt Ltd", "M&A", "deal"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "schedule of investor meet", "investor_meetings", "meet"),
    ("Earnings Call Transcript", "", "earnings_call", "transcript"),
    ("Disclosure under Regulation 31 of SAST - creation of pledge", "", "pledging", "pledge"),
    ("ESOP/ESOS/ESPS", "allotment of shares under ESOP", "unclassified", "routine"),
    ("Press Release", "receipt of order worth Rs 500 crore", "press_release", "order"),
    ("Notice of Postal Ballot", "", "postal_ballot", "ballot"),
    ("Dividend", "interim dividend of Rs 5 per share", "dividend", "dividend"),
    ("Updates", "Buyback of equity shares approved", "fund_raise", "buyback"),
    ("Reference to the Financial Results issued by Suzuki Motor Corporation", "", "press_release", "update"),
]


@pytest.mark.parametrize("title,body,cat,sub", CASES)
def test_rules_classify(title, body, cat, sub):
    c = classify.classify({"title": title, "body": body})
    assert (c["category"], c["subtype"]) == (cat, sub)


def test_unknown_filing_is_not_silently_buried():
    c = classify.classify({"title": "General Updates", "body": "Intimation"})
    assert c["by"] == "none" and c["score"] >= 30


def test_moves_respect_thresholds():
    rows = [{"d": f"2026-10-{i + 1:02d}", "c": 100.0, "v": 1000} for i in range(25)]
    rows.append({"d": "2026-10-26", "c": 103.0, "v": 2600})
    px = {"symbol": "X", "rows": rows}
    hits, last = moves.scan(px, {"vol": 2, "px": 4, "lookback": 20})
    assert [h["kinds"] for h in hits] == [["volume"]] and last["volx"] == 2.6 and last["pct"] == 3.0
    assert [h["kinds"] for h in moves.scan(px, {"vol": 3, "px": 2.5, "lookback": 20})[0]] == [["price"]]
    assert moves.scan(px, {"vol": 3, "px": 4, "lookback": 20})[0] == []


def test_guidance_regex_extraction():
    pages = ["Analyst: Will margins hold at 20%?", "CEO: For FY27, we are guiding for revenue growth of 13% to 15%. "
             "We expect EBITDA margin of around 19% this year. We plan capex of Rs 1,250 crore in FY2026-27. The weather was 30% wetter."]
    got = {(g["metric"], g["lo"], g["hi"], g["fy"]) for g in guidance.regex_extract(pages, "Apr 2026", "u")}
    assert got == {("revenue_growth", 13.0, 15.0, 2027), ("ebitda_margin", 19.0, 19.0, 2027), ("capex", 1250.0, 1250.0, 2027)}


def test_said_vs_did_is_arithmetic():
    co = {"quarters": {"cols": ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
                       "rows": {"sales": [100, 100, 100, 100, 108, 110], "operating_profit": [20, 20, 20, 20, 19, 20], "net_profit": [10] * 6}},
          "pnl": {"cols": ["Mar 2025", "Mar 2026"], "rows": {"sales": [350, 400], "operating_profit": [70, 76], "net_profit": [35, 40]}}}
    items = [{"metric": "revenue_growth", "lo": 13, "hi": 15, "unit": "pct", "fy": 2027, "said_on": "Apr 2026", "quote": "", "page": 1, "url": ""},
             {"metric": "revenue_growth", "lo": 9, "hi": 10, "unit": "pct", "fy": 2027, "said_on": "Oct 2026", "quote": "", "page": 1, "url": ""},
             {"metric": "revenue_growth", "lo": 12, "hi": 15, "unit": "pct", "fy": 2026, "said_on": "Jul 2025", "quote": "", "page": 1, "url": ""},
             {"metric": "ebitda_margin", "lo": 20, "hi": 21, "unit": "pct", "fy": 2026, "said_on": "Jul 2025", "quote": "", "page": 1, "url": ""}]
    sc = guidance.scorecard(guidance.evaluate(items, co))
    t = {(x["metric"], x["fy"]): x for x in sc["threads"]}
    fy27 = t[("revenue_growth", 2027)]
    assert fy27["actual"] == 9.0 and fy27["period"] == "H1 FY27" and fy27["moved"] == "cut"
    assert fy27["verdict_vs_first"] == "behind" and fy27["verdict_vs_last"] == "on_track"
    assert t[("revenue_growth", 2026)]["actual"] == 14.3 and t[("revenue_growth", 2026)]["verdict_vs_first"] == "met"
    assert t[("ebitda_margin", 2026)]["actual"] == 19.0 and t[("ebitda_margin", 2026)]["verdict_vs_first"] == "missed"
    assert (sc["checked"], sc["kept"], sc["cuts"]) == (3, 1, 1)


def test_commands():
    assert commands.parse("alert me if volume is over 3x")["patch"] == {"vol": 3.0}
    assert commands.parse("flag price moves above 5%")["patch"] == {"px": 5.0}
    assert commands.parse("what changed this week") == {"intent": "digest", "window": "7d"}
    assert commands.parse("KAVERI")["intent"] == "research"
    assert commands.parse("what did KAVERI say about leverage?")["intent"] == "ask"


# ---- model router against a local OpenAI-compatible stub ------------------------------
class Stub(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.calls.append(body["model"])
        sys_p = body["messages"][0]["content"]
        if "classify" in sys_p:
            out = {"items": [{"n": 1, "category": "litigation", "materiality": 81}]}
        else:
            out = {"items": [{"metric": "revenue_growth", "lo": 12, "hi": 14, "unit": "pct", "fy": 2027, "quote": "we guide 12 to 14", "page": 2}]}
        data = json.dumps({"choices": [{"message": {"content": "```json\n" + json.dumps(out) + "\n```"}}],
                           "usage": {"prompt_tokens": 50, "completion_tokens": 20}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def stub_llm(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "LLM_BASE", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(config, "LLM_KEY", "test")
    monkeypatch.setattr(config, "MODEL_CHEAP", "cheap-model")
    monkeypatch.setattr(config, "MODEL_STRONG", "strong-model")
    Stub.calls.clear()
    yield
    srv.shutdown()


def test_model_routing_fallback_and_cache(stub_llm):
    it = {"id": "zz1", "symbol": "X", "title": "General Updates", "body": "Order received from regulator"}
    c = classify.classify_many([it, {"id": "zz2", "symbol": "X", "title": "Trading Window", "body": ""}])
    assert c["zz1"] == {"category": "litigation", "subtype": "model", "by": "model", "score": 81}
    assert c["zz2"]["by"] == "rules" and Stub.calls == ["cheap-model"]      # only the ambiguous one cost a call
    classify.classify_many([it])
    assert Stub.calls == ["cheap-model"]                                     # second time is free
    g = guidance.llm_extract(["x", "We expect growth and guide 12 to 14"], "Apr 2026", "u")
    assert g[0]["lo"] == 12 and g[0]["by"] == "model"
    before = llm.LEDGER["cheap"]["cache_hits"]
    guidance.llm_extract(["x", "We expect growth and guide 12 to 14"], "Apr 2026", "u")
    assert llm.LEDGER["cheap"]["cache_hits"] == before + 1 and len(Stub.calls) == 2


# ---- API, end to end on the sample universe ------------------------------------------
def test_api_end_to_end():
    c = app.test_client()
    assert c.get("/api/meta").json["sample"] is True
    d = c.get("/api/digest?window=24h").json
    assert d["counts"]["act"] >= 3 and d["counts"]["buried"] > d["counts"]["act"] and d["spoken"]
    res = next(i for i in d["act"] if i["enrich_kind"] == "results")
    assert res["related"] and res["move"]["pct"] < 0
    e = c.get(f"/api/enrich/{res['id']}").json
    assert e["status"] == "ok" and [r["label"] for r in e["rows"]] == ["Revenue", "EBITDA", "PBT", "PAT"]
    mg = next(i for i in d["act"] if i["enrich_kind"] == "management")
    e = c.get(f"/api/enrich/{mg['id']}").json
    assert e["changes"][0]["action"] == "appointed" and e["changes"][0]["bio"]
    strict = c.get("/api/digest?window=24h&vol=5&px=10").json
    assert strict["counts"]["moves"] < d["counts"]["moves"]
    muted = c.get("/api/digest?window=24h&mute=results,M%26A,management_change&care=").json
    assert muted["counts"]["act"] < d["counts"]["act"]
    assert c.get("/api/digest?from=nonsense").status_code == 400
    for _ in range(100):
        j = c.get("/api/research/TARANG").json
        if j["state"] != "running":
            break
        time.sleep(0.05)
    assert j["state"] == "done" and len(j["cards"]) == 4 and j["said_did"]["checked"] >= 3
    a = c.post("/api/ask", json={"symbol": "TARANG", "question": "what about capex?"}).json
    assert any("capex" in p["text"].lower() for p in a["passages"])
    assert c.get("/api/research/NOSUCH").json["state"] in ("running", "error")
    assert sources.SAMPLE


SEBI_FILING = """Sub: Intimation under Regulation 30 of SEBI (LODR) Regulations, 2015 - Change in Director(s)
Sr. No. Particulars Details
1 Reason for change viz. appointment, re-appointment, resignation, removal, death or otherwise Appointment of Mr. V. Srinivasa Rangan as an Additional Independent Director of the Bank. Resignation of Ms. Renu Karnad Non-Executive Director due to completion of tenure.
2 Date of appointment / cessation & term of appointment November 13, 2026 for a period of three years
3 Brief profile (in case of appointment) As provided in Annexure II.
4 Disclosure of relationships between directors (in case of appointment of a director) None

Annexure II
Brief Profile of Mr. V. Srinivasa Rangan
Mr. Rangan has over 35 years of experience in financial services. He previously served as Executive Director and CFO of a housing finance company. He is a Chartered Accountant and holds a degree in commerce.

Yours faithfully, For the Bank"""


def test_management_change_from_a_table_style_filing_without_a_model():
    from finn import enrich
    ch = enrich._mgmt_rules(SEBI_FILING)
    by = {c["name"]: c for c in ch}
    assert set(by) == {"Mr V. Srinivasa Rangan", "Ms Renu Karnad"}
    assert by["Mr V. Srinivasa Rangan"]["action"] == "appointed" and by["Mr V. Srinivasa Rangan"]["role"] == "Independent Director"
    assert by["Ms Renu Karnad"]["action"] == "resigned"
    bio = by["Mr V. Srinivasa Rangan"]["bio"]
    assert len(bio) == 3 and "35 years" in bio[0] and not any("Annexure" in b for b in bio)
    # a filing whose profile is only a pointer yields no bio rather than a wrong one
    assert enrich._mgmt_rules(SEBI_FILING.split("Annexure II\n")[0])[0]["bio"] == []


def test_an_analysts_number_is_never_recorded_as_management_guidance():
    pages = ["Moderator: The next question is from the line of Ankur Rudra from JP Morgan. Please go ahead.\n"
             "Ankur Rudra: Thank you. To get back towards 26%, which is the aspirational\nmargin, do you\nneed growth to improve? "
             "I expect margin of 24% to 25% this year.\n"
             "Samir Seksaria: Thanks Ankur. We expect EBITDA margin of 25% to\n26% for FY27 as the wage cycle is behind us.",
             "We are guiding for revenue growth of 8% to\n10% in FY27.\nAnkur Rudra: Understood, will revenue growth of 12% be the target next year."]
    got = [(g["metric"], g["lo"], g["hi"], g["page"]) for g in guidance.regex_extract(pages, "Oct 2026", "u")]
    assert got == [("ebitda_margin", 25.0, 26.0, 1), ("revenue_growth", 8.0, 10.0, 2)]


def test_reported_results_are_not_guidance():
    pages = ["K Krithivasan: We maintained a strong focus on execution to deliver an operating margin of 25%. "
             "Revenue growth was 11% and we expect the momentum to continue. Our EBITDA margin for the quarter stood at 24.5%, which we expect to sustain. "
             "Going forward, we expect EBITDA margin of 25% to 26% for FY27."]
    got = [(g["metric"], g["lo"], g["hi"]) for g in guidance.regex_extract(pages, "Apr 2026", "u")]
    assert got == [("ebitda_margin", 25.0, 26.0)]


def test_segment_quarterly_and_long_term_targets_are_labelled_and_never_graded():
    pages = ["Atul Lall: Over the past few weeks, supply-demand dynamics are becoming more balanced and we expect 12% to 15% growth quarter-on-quarter in the smartphones volume.",
             "Polycab India Limited May 06, 2026 Page 8 of 18\nInder Jaisinghani: Looking ahead, we remain on track to achieve EBITDA margins in the range of 8% to 10% by FY30 in the FMEG segment. "
             "Over long term, we should expect 11% to 13% EBITDA margin. For FY27, we are guiding for revenue growth of 18% to 20%. We expect margin of 13% to 14%."]
    got = guidance.regex_extract(pages, "May 2026", "u")
    assert [(g["metric"], g["label"], g["lo"]) for g in got] == [
        ("other", "Volume growth (quarterly)", 12.0), ("other", "EBITDA margin (segment)", 8.0),
        ("other", "EBITDA margin (long term)", 11.0), ("revenue_growth", None, 18.0), ("margin", None, 13.0)]
    assert not any("Page 8" in g["quote"] for g in got)
    co = {"quarters": {"cols": ["Jun 2025", "Sep 2025", "Jun 2026", "Sep 2026"], "rows": {"sales": [1, 1, 1, 1], "operating_profit": [0.1] * 4}},
          "pnl": {"cols": ["Mar 2026"], "rows": {"sales": [4], "operating_profit": [0.4]}}}
    sc = guidance.scorecard(guidance.evaluate(got, co))
    t = sc["threads"]
    assert len(t) == 5 and t[0]["metric"] == "revenue_growth" and t[0]["year_stated"]
    assert [x["verdict_vs_first"] for x in t if x["metric"] == "other"] == ["unverifiable"] * 3
    undated = next(x for x in t if x["metric"] == "margin")
    assert undated["year_stated"] is False and undated["verdict_vs_first"] == "unverifiable"


def test_operating_margin_is_graded_as_ebit_not_ebitda():
    co = {"quarters": {"cols": ["Jun 2026", "Sep 2026"], "rows": {"sales": [100, 100], "operating_profit": [27, 27], "depreciation": [2, 2]}},
          "pnl": {"cols": ["Mar 2026"], "rows": {"sales": [400], "operating_profit": [108], "depreciation": [8]}}}
    pages = ["CFO: We expect operating margin of 26% to 28% for FY27. We expect EBITDA margin of 26% to 28% for FY27."]
    ev = guidance.evaluate(guidance.regex_extract(pages, "Apr 2026", "u"), co)
    got = {e["metric"]: (e["actual"], e["verdict"]) for e in ev}
    assert got == {"ebit_margin": (25.0, "behind"), "ebitda_margin": (27.0, "on_track")}
