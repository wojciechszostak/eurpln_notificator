import re
from datetime import datetime
from typing import Dict
import requests
from bs4 import BeautifulSoup
from config import TZ

NUM_RE = re.compile(r"[-+]?\d+[.,]?\d*")

URL = "https://pl.investing.com/currencies/eur-pln"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_html(url: str = URL, timeout: int = 15) -> str:
    """Pobiera surowy HTML ze strony Investing."""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_tick(html: str) -> Dict[str, str]:
    """Parsuje kurs EUR/PLN, zmianę, procentową zmianę i kurs otwarcia."""
    soup = BeautifulSoup(html, "html.parser")

    kurs = soup.select_one('div[data-test="instrument-price-last"]')
    zmiana = soup.select_one('span[data-test="instrument-price-change"]')
    zmiana_pct = soup.select_one('span[data-test="instrument-price-change-percent"]')

    # kurs otwarcia
    kurs_otwarcia = ""
    node = soup.select_one('dd[data-test="open"] span.key-info_dd-numeric__ZQFIs > span:nth-of-type(2)')
    if node:
        val = node.get_text(strip=True)
        if val and NUM_RE.search(val):
            kurs_otwarcia = val

    # usunięcie nawiasów z wartości procentowej zmiany
    zmiana_pct_val = ""
    if zmiana_pct:
        zmiana_pct_val = zmiana_pct.get_text(strip=True).replace("(", "").replace(")", "")

    now = datetime.now(tz=TZ).isoformat(timespec="seconds")
    return {
        "timestamp": now,
        "kurs": kurs.get_text(strip=True) if kurs else "",
        "zmiana": zmiana.get_text(strip=True) if zmiana else "",
        "zmiana_pct": zmiana_pct_val,
        "kurs_otwarcia": kurs_otwarcia or "",
    }


def get_eurpln_snapshot() -> Dict[str, str]:
    """Pobiera i parsuje aktualny snapshot EUR/PLN."""
    html = fetch_html()
    return parse_tick(html)
