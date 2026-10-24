"""Resource gathering tests: EDGAR is faked, so no network is needed."""
import os

os.environ["BROKER_MODE"] = "mock"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.resources import Resources, parse_edgar  # noqa: E402

EDGAR_SAMPLE = {
    "hits": {
        "hits": [
            {"_id": "0001193125-26-360128:d135723d424b3.htm",
             "_source": {"ciks": ["0002063380"], "display_names": ["Fidelity Solana Fund  (CIK 0002063380)"], "file_date": "2026-08-21", "form": "424B3", "adsh": "0001193125-26-360128"}},
            {"_id": "0001193125-26-360128:ex99.htm",
             "_source": {"ciks": ["0002063380"], "display_names": ["Fidelity Solana Fund  (CIK 0002063380)"], "file_date": "2026-08-21", "form": "424B3", "adsh": "0001193125-26-360128"}},
            {"_id": "0001104659-26-086351:tm2534148-9_424b3.htm",
             "_source": {"ciks": ["0002103547"], "display_names": ["Morgan Stanley Solana Trust  (CIK 0002103547)"], "file_date": "2026-07-23", "form": "424B3"}},
            {"_id": "broken", "_source": {}},
        ]
    }
}


def test_parse_edgar_builds_real_archive_links_and_dedupes():
    items = parse_edgar(EDGAR_SAMPLE)
    assert len(items) == 2
    assert items[0]["date"] == "2026-08-21"
    assert items[0]["url"] == "https://www.sec.gov/Archives/edgar/data/2063380/000119312526360128/d135723d424b3.htm"
    assert items[1]["publisher"] == "Morgan Stanley Solana Trust"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gather_with_live_edgar():
    seen = {}

    def handler(req: httpx.Request):
        seen["q"] = req.url.params["q"]
        return httpx.Response(200, json=EDGAR_SAMPLE)

    r = Resources(get_settings(), _client(handler)).gather("sol")
    assert seen["q"] == '"Solana"'
    assert r["edgar_ok"] and len(r["recent_filings"]) == 2 and len(r["vetted"]) == 3
    assert "Fidelity Solana Fund" in r["say"] and "not recommendations" in r["say"]


def test_gather_survives_edgar_outage():
    r = Resources(get_settings(), _client(lambda req: httpx.Response(503))).gather("ETH")
    assert r["edgar_ok"] is False and r["vetted"] and "couldn't reach SEC EDGAR" in r["say"]


def test_unsupported_asset():
    assert Resources(get_settings(), _client(lambda req: httpx.Response(200, json={}))).gather("DOGE")["error"] == "unsupported"
