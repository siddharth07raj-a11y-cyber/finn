"""HTTP API + static frontend. The server is stateless: the client owns the portfolio
and alert rules and sends them with each request, so the app survives free-tier
restarts and several people can try it at once without stepping on each other."""
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import cache, classify, commands, config, digest, enrich, llm, research, sources

WEB = Path(__file__).resolve().parent.parent / "web"
app = Flask(__name__, static_folder=None)


def _rules():
    r = dict(config.DEFAULT_RULES)
    a = request.args
    for k, cast in (("vol", float), ("px", float), ("lookback", int)):
        if a.get(k):
            try:
                r[k] = cast(a[k])
            except ValueError:
                pass
    r["vol"], r["px"], r["lookback"] = max(1.1, min(r["vol"], 20)), max(0.5, min(r["px"], 50)), max(3, min(r["lookback"], 120))
    for k in ("care", "mute"):
        if k in a:
            r[k] = [c for c in a[k].split(",") if c in classify.CATEGORIES]
    return r


def _symbols():
    raw = request.args.get("symbols", "")
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()][:30]
    return syms or sources.portfolio()


@app.get("/api/meta")
def meta():
    return jsonify({"sample": sources.SAMPLE, "portfolio": sources.portfolio(), "picks": sources.research_picks(),
                    "rules": config.DEFAULT_RULES, "llm": llm.status(),
                    "categories": [{"key": c, "label": classify.LABEL[c]} for c in classify.CATEGORIES]})


@app.get("/api/digest")
def api_digest():
    try:
        start, end, label = digest.window(request.args.get("window", "24h"), request.args.get("from"), request.args.get("to"))
    except ValueError:
        return jsonify({"error": "Dates must look like 2026-11-01."}), 400
    d = digest.build(_symbols(), start, end, label, _rules())
    d["spoken"] = digest.spoken(d)
    return jsonify(d)


@app.get("/api/enrich/<item_id>")
def api_enrich(item_id):
    rec, _ = cache.get("item:" + item_id)
    if not rec:
        return jsonify({"status": "unavailable"}), 404
    return jsonify(enrich.enrich(rec["item"], rec["cls"]) or {"status": "unavailable"})


@app.get("/api/research/<symbol>")
def api_research(symbol):
    job = research.get(symbol, refresh=request.args.get("refresh") == "1")
    return jsonify({k: v for k, v in job.items() if k != "t"})


@app.post("/api/ask")
def api_ask():
    b = request.get_json(silent=True) or {}
    if not b.get("symbol") or not b.get("question"):
        return jsonify({"error": "Need a symbol and a question."}), 400
    try:
        return jsonify(research.ask(b["symbol"], b["question"][:400]))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@app.post("/api/command")
def api_command():
    b = request.get_json(silent=True) or {}
    return jsonify(commands.parse(b.get("text", "")[:300], b.get("symbol")))


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    try:
        return jsonify(sources.search(q)[:8] if len(q) >= 2 else [])
    except Exception:  # noqa: BLE001
        return jsonify([])


@app.get("/api/status")
def api_status():
    return jsonify({"mode": config.DATA_MODE, "llm": llm.status()})


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(WEB, path)
