"""Shared HTTP session: browser-like headers, timeouts, small retry."""
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
BASE_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def new_session():
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    return s


_session = new_session()


def get(url, *, headers=None, params=None, timeout=20, retries=1, session=None, stream=False):
    s = session or _session
    last = None
    for attempt in range(retries + 1):
        try:
            r = s.get(url, headers=headers, params=params, timeout=timeout, stream=stream)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise last
