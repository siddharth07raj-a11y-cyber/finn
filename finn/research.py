"""Pull: on-demand research for ANY NSE ticker, grounded in primary sources.

Sources used: the company's standardised statements, its concall transcripts and its
annual report. No news, broker notes or model memory. Work is staged so the phone
gets something immediately:

  stage 0 (instant, no model)   financial snapshot, trajectory, balance sheet, cash quality
  stage 1 (cheap model / rules) guidance ledger from the last five transcripts -> said vs did
  stage 2 (cheap model)         business snapshot from the annual report
  stage 3 (ONE strong call)     narrative vs numbers + bull / bear, written only from the
                                facts computed in stages 0-2
"""
import math
import re
import threading
import time
from collections import Counter

from . import analytics, cache, guidance, llm, sources

JOBS = {}
_lock = threading.Lock()
STOP = set("the a an of to in for and or on at by with is are was were be been this that it as from our we you your "
           "what how did does do about say said management company".split())


def _tokens(s):
    return [w for w in re.findall(r"[a-z][a-z0-9&\-]{2,}", s.lower()) if w not in STOP]


def retrieve(question, docs, k=6):
    """Lexical page retrieval (TF-IDF). No embeddings, no model: free and good enough
    for documents that use the same vocabulary as the question."""
    q = set(_tokens(question))
    chunks = []
    for d in docs:
        for pno, text in enumerate(d["pages"], 1):
            if len(text) > 80:
                chunks.append((d, pno, text, Counter(_tokens(text))))
    if not chunks or not q:
        return []
    df = Counter(t for c in chunks for t in c[3] if t in q)
    scored = []
    for d, pno, text, tf in chunks:
        s = sum((1 + math.log(tf[t])) * math.log(1 + len(chunks) / df[t]) for t in q if tf.get(t))
        if s > 0:
            scored.append((s / (1 + 0.15 * math.log(1 + len(text) / 2000)), d, pno, text))
    scored.sort(key=lambda x: -x[0])
    return [{"doc": d["title"], "url": d["url"], "page": pno, "text": text} for _, d, pno, text in scored[:k]]


def _load_docs(co, job, n_calls=5, with_ar=False):
    docs = []
    for c in [c for c in co["docs"]["concalls"] if c.get("transcript")][:n_calls]:
        job["stage"] = f"Reading the {c['date']} call transcript"
        try:
            pages = sources.doc_pages(c["transcript"])
        except Exception as e:  # noqa: BLE001
            job["skipped"].append({"doc": f"{c['date']} transcript", "why": str(e)[:100]})
            continue
        if sum(len(p) for p in pages) < 400:
            job["skipped"].append({"doc": f"{c['date']} transcript", "why": "scanned PDF, no text layer"})
            continue
        docs.append({"kind": "transcript", "title": f"{c['date']} concall", "date": c["date"], "url": c["transcript"], "pages": pages})
    if with_ar and co["docs"]["annual_reports"]:
        ar = co["docs"]["annual_reports"][0]
        job["stage"] = f"Reading the annual report ({ar['title']})"
        try:
            pages = sources.doc_pages(ar["url"])
            if sum(len(p) for p in pages) > 400:
                docs.append({"kind": "annual_report", "title": f"Annual report, {ar['title']}", "url": ar["url"], "pages": pages})
            else:
                job["skipped"].append({"doc": "annual report", "why": "scanned PDF, no text layer"})
        except Exception as e:  # noqa: BLE001
            job["skipped"].append({"doc": "annual report", "why": str(e)[:100]})
    return docs


BIZ_SYSTEM = """You describe what a company does using ONLY the annual-report excerpts provided (each tagged with a page).
Return JSON: {"what":"one plain sentence, max 30 words","segments":[{"name":"...","share_pct":number or null}],
"mix_basis":"what the shares are a share of, e.g. revenue by segment","facts":["up to 3 short operating facts with numbers"],"pages":[page numbers used]}
If the excerpts do not state something, leave it out. Never use outside knowledge."""

READ_SYSTEM = """You are a buy-side analyst writing for a portfolio manager on a phone. You are given FACTS computed from a company's
own statements, a ledger of what management guided versus what was reported, and management's latest opening remarks.
Use ONLY these. Do not use outside knowledge of the company. Every bullet must rest on a number or statement in the input.
Return JSON: {"read":"two sentences: where management's story and the numbers agree, and where they diverge",
"agree":["max 2 bullets"],"diverge":["max 3 bullets"],"bull":["3 bullets"],"bear":["3 bullets"]}
Each bullet max 22 words, plain English, no hedging filler.
Lines marked UNGRADED are segment, quarterly, long-term or undated targets: never compare them with company-level figures.
For banks and lenders do not comment on operating or financing margin."""


def _facts(cards, sc):
    lines = []
    for c in cards:
        if c.get("verdict", {}).get("text"):
            lines.append(f"{c['title']}: {c['verdict']['text']}")
        for s in c.get("stats", []):
            if s["value"] is not None:
                lines.append(f"  {s['label']}: {s['value']} {s['unit']}")
    for t in sc["threads"]:
        said = "; ".join(f"{s['said_on']}: {s['lo']:g}-{s['hi']:g}" for s in t["said"])
        if t["actual"] is None:
            lines.append(f"UNGRADED target, {t['label']} ({t['unit']}): {said}")
            continue
        lines.append(f"Guidance {t['label']} FY{t['fy'] % 100} ({t['unit']}): {said} | reported {t['actual']} for {t['period']} | "
                     f"vs first number: {t['verdict_vs_first']}" + (f" | guidance was {t['moved']}" if t["moved"] else ""))
    return "\n".join(lines)


def _rule_cases(cards, sc):
    bull, bear = [], []
    for c in cards:
        v = c.get("verdict") or {}
        if v.get("tone") == "good":
            bull.append(v["text"])
        elif v.get("tone") in ("bad", "warn"):
            bear.append(v["text"])
    for t in sc["threads"]:
        if t["actual"] is None:
            continue
        s = t["said"][0]
        line = f"{t['label']} for FY{t['fy'] % 100}: guided {s['lo']:g}–{s['hi']:g}% in {s['said_on']}, reported {t['actual']:g}% for {t['period']}"
        (bull if t["verdict_vs_first"] in ("met", "beat", "on_track", "ahead") else bear).append(line + ".")
    return bull[:3], bear[:3]


def _run(symbol, job):
    try:
        co, meta = sources.company(symbol)
        job.update(name=co["name"], symbol=co["symbol"], sector=co.get("sector"), basis="Consolidated" if co.get("consolidated") else "Standalone",
                   source_url=co.get("url"), stale=meta.get("stale", False), is_financial=co.get("is_financial", False))
        cards = analytics.cards(co)
        job["cards"] = cards
        job["about"] = co.get("about", "")
        job["stage"] = "Finding transcripts"

        docs = _load_docs(co, job, with_ar=llm.ready())
        job["sources"] = [{"title": d["title"], "url": d["url"], "pages": len(d["pages"]), "kind": d["kind"]} for d in docs]
        with _lock:
            DOCS[symbol] = docs

        # stage 1: guidance -> said vs did (code does the comparison)
        items = []
        for d in [d for d in docs if d["kind"] == "transcript"]:
            job["stage"] = f"Extracting guidance from the {d['date']} call"
            items += guidance.extract(d["pages"], d["date"], d["url"])
        sc = guidance.scorecard(guidance.evaluate(items, co))
        sc["read"] = guidance.read(sc)
        sc["by"] = "model" if any(i.get("by") == "model" for i in items) else "rules"
        sc["calls_read"] = [d["date"] for d in docs if d["kind"] == "transcript"]
        job["said_did"] = sc

        # stage 2: business snapshot from the annual report
        ar = next((d for d in docs if d["kind"] == "annual_report"), None)
        if ar and llm.ready():
            job["stage"] = "Reading the business overview"
            hits = retrieve("business overview segment revenue mix share products geography customers capacity", [ar], k=6)
            text = "\n\n".join(f"[page {h['page']}]\n{h['text'][:3500]}" for h in hits)
            biz = llm.chat_json("cheap", BIZ_SYSTEM, text, max_tokens=700)
            if isinstance(biz, dict) and biz.get("what"):
                job["business"] = {**biz, "source": ar["title"], "url": ar["url"]}

        # stage 3: one strong call over compact facts (never over raw documents)
        bull, bear = _rule_cases(cards, sc)
        job["cases"] = {"bull": bull, "bear": bear, "by": "rules"}
        if llm.ready():
            job["stage"] = "Writing the read"
            calls = [d for d in docs if d["kind"] == "transcript"]
            remarks = "\n".join(calls[0]["pages"][:3])[:5000] if calls else ""
            res = llm.chat_json("strong", READ_SYSTEM,
                                f"COMPANY: {co['name']}\n\nFACTS\n{_facts(cards, sc)}\n\nMANAGEMENT'S LATEST OPENING REMARKS ({calls[0]['date'] if calls else 'n/a'})\n{remarks}",
                                max_tokens=900)
            if isinstance(res, dict) and res.get("read"):
                job["narrative"] = {k: res.get(k) for k in ("read", "agree", "diverge")}
                if res.get("bull") and res.get("bear"):
                    job["cases"] = {"bull": res["bull"][:3], "bear": res["bear"][:3], "by": "model"}
        job["state"], job["stage"] = "done", ""
        if not sources.SAMPLE:
            cache.put(_ckey(symbol), {k: v for k, v in job.items() if k != "t"})
    except Exception as e:  # noqa: BLE001
        job["state"], job["error"] = "error", str(e)[:300]


DOCS = {}


def _ckey(symbol):
    """Saved research is kept separately for the with-model and without-model paths."""
    return f"research9:{'m' if llm.ready() else 'r'}:{symbol}"


def get(symbol, refresh=False):
    """Start (or return) the research job for a symbol. Poll until state == 'done'."""
    symbol = symbol.upper().strip()
    with _lock:
        job = JOBS.get(symbol)
        if job and not refresh and (job["state"] == "running" or time.time() - job["t"] < 6 * 3600):
            return job
        if not refresh and not sources.SAMPLE:
            hit, _ = cache.get(_ckey(symbol), ttl=12 * 3600)
            if hit:
                hit["t"] = time.time()
                JOBS[symbol] = hit
                return hit
        job = {"symbol": symbol, "state": "running", "stage": "Loading financials", "t": time.time(),
               "cards": [], "skipped": [], "sources": [], "llm": llm.ready(), "sample": sources.SAMPLE}
        JOBS[symbol] = job
    threading.Thread(target=_run, args=(symbol, job), daemon=True).start()
    return job


ASK_SYSTEM = """Answer the investor's question about a company using ONLY the excerpts provided (transcripts and annual report).
Be direct: 2-4 sentences, lead with the answer, include the numbers management gave. Cite like [Jul 2026 concall p.4].
If the excerpts do not answer it, say so plainly. Never use outside knowledge."""


def ask(symbol, question):
    symbol = symbol.upper().strip()
    docs = DOCS.get(symbol)
    if docs is None:
        co, _ = sources.company(symbol)
        job = {"skipped": [], "stage": ""}
        docs = _load_docs(co, job, with_ar=False)
        with _lock:
            DOCS[symbol] = docs
    hits = retrieve(question, docs, k=5)
    passages = []
    qtok = set(_tokens(question))
    for h in hits:  # show the sentences that carry the match, not the whole page
        sents = re.split(r"(?<=[.?!])\s+|\n+", h["text"])
        best = [s for s in sorted(sents, key=lambda s: -len(qtok & set(_tokens(s)))) if qtok & set(_tokens(s))][:2] or sents[:1]
        passages.append({"doc": h["doc"], "page": h["page"], "url": h["url"], "text": " ".join(b.strip() for b in best)[:420]})
    answer = None
    if hits and llm.ready():
        ctx = "\n\n".join(f"[{h['doc']} p.{h['page']}]\n{h['text'][:3000]}" for h in hits)
        answer = llm.chat("cheap", ASK_SYSTEM, f"QUESTION: {question}\n\nEXCERPTS\n{ctx}", json_mode=False, max_tokens=400)
    return {"symbol": symbol, "question": question, "answer": answer, "passages": passages,
            "docs_searched": len(docs), "llm": llm.ready()}
