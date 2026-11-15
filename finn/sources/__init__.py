"""Data access. Every call is cached; live mode falls back to the last good answer."""
from datetime import datetime, timedelta

from .. import cache, config
from . import announcements as _ann, documents as _docs, prices as _prices, sample, screener as _scr

SAMPLE = config.DATA_MODE == "sample"


def portfolio():
    return sample.PORTFOLIO if SAMPLE else config.PORTFOLIO


def research_picks():
    return sample.RESEARCH_PICKS if SAMPLE else config.RESEARCH_PICKS


def prices(symbol):
    if SAMPLE:
        return sample.history(symbol), {"stale": False}
    return cache.cached(f"px:{symbol}", 30 * 60, lambda: _prices.history(symbol))


def company(symbol):
    if SAMPLE:
        return sample.company(symbol), {"stale": False}
    return cache.cached(f"co:{symbol}", 6 * 3600, lambda: _scr.company(symbol))


def announcements(symbol, days=30):
    """All filings for a symbol over the last `days` days (windowing happens downstream)."""
    end = datetime.now(config.IST).date()
    start = end - timedelta(days=days)
    if SAMPLE:
        return sample.announcements(symbol, start, end), {"stale": False}

    def resolve():
        try:
            return company(symbol)[0]
        except Exception:  # noqa: BLE001
            return None

    def go():
        return _ann.fetch(symbol, start, end, resolve=resolve)

    return cache.cached(f"ann:{symbol}:{days}", 10 * 60, go)


def doc_pages(url):
    if url.startswith("sample://"):
        return sample.doc_pages(url)
    return _docs.pages(url)


def search(q):
    if SAMPLE:
        return sample.search(q)
    return cache.cached(f"search:{q.lower()}", 24 * 3600, lambda: _scr.search(q))[0]
