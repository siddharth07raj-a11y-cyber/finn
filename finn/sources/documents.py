"""Download a filing / transcript / annual-report PDF once and keep its page text.

Documents are immutable, so both the PDF and the extracted pages are cached forever
by URL hash. Everything downstream (retrieval, extraction) works on page text.
"""
import hashlib
import io
import json
import re

from .. import http
from ..config import DATA_DIR

DOCS = DATA_DIR / "docs"
DOCS.mkdir(exist_ok=True)
MAX_BYTES = 80 * 1024 * 1024
MAX_PAGES = 600


def _candidates(url):
    """BSE serves the same attachment from a viewer page and two static folders."""
    urls = [url]
    m = re.search(r"AnnPdfOpen\.aspx\?Pname=([\w\-]+\.pdf)", url, re.I) or \
        re.search(r"corpfiling/Attach(?:Live|His)/([\w\-]+\.pdf)", url, re.I)
    if m:
        f = m.group(1)
        for u in (f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{f}",
                  f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{f}",
                  f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={f}"):
            if u not in urls:
                urls.append(u)
    return urls


def _download(url):
    last = None
    for u in _candidates(url):
        try:
            headers = {"Referer": "https://www.bseindia.com/"} if "bseindia" in u else \
                      {"Referer": "https://www.nseindia.com/"} if "nseindia" in u else None
            r = http.get(u, headers=headers, timeout=45, stream=True)
            buf = io.BytesIO()
            for chunk in r.iter_content(1 << 16):
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    raise ValueError("document larger than 80 MB")
            data = buf.getvalue()
            if data[:1024].lstrip().startswith(b"%PDF"):
                return data
            last = ValueError("not a PDF")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def extract_pages(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, p in enumerate(reader.pages):
        if i >= MAX_PAGES:
            break
        try:
            t = p.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        pages.append(re.sub(r"[ \t]+", " ", t).strip())
    return pages


def pages(url):
    """List of page texts for a PDF URL. Scanned PDFs return empty strings."""
    f = DOCS / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text())
    out = extract_pages(_download(url))
    f.write_text(json.dumps(out))
    return out


def has_text(pgs):
    return sum(len(p) for p in pgs) > 400
