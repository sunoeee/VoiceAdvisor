"""Static facts about assets the user might ask about.

Used only to give the model accurate, stable context (what kind of asset it
is). Extend the table as needed; unknown symbols are handled gracefully.
"""

ASSETS: dict[str, dict] = {
    # Crypto
    "BTC": {"name": "Bitcoin", "category": "crypto", "sector": "crypto", "type": "cryptocurrency"},
    "ETH": {"name": "Ethereum", "category": "crypto", "sector": "crypto", "type": "cryptocurrency"},
    "SOL": {"name": "Solana", "category": "crypto", "sector": "crypto", "type": "cryptocurrency"},
    "USDC": {"name": "USD Coin", "category": "cash", "sector": "cash", "type": "stablecoin"},
    # Stocks (tokenized stocks are available on the True Markets Gateway)
    "NVDA": {"name": "NVIDIA", "category": "stock", "sector": "technology", "type": "single stock"},
    "AAPL": {"name": "Apple", "category": "stock", "sector": "technology", "type": "single stock"},
    "MSFT": {"name": "Microsoft", "category": "stock", "sector": "technology", "type": "single stock"},
    "GOOGL": {"name": "Alphabet", "category": "stock", "sector": "technology", "type": "single stock"},
    "AMZN": {"name": "Amazon", "category": "stock", "sector": "consumer and technology", "type": "single stock"},
    "META": {"name": "Meta", "category": "stock", "sector": "technology", "type": "single stock"},
    "TSLA": {"name": "Tesla", "category": "stock", "sector": "automotive and technology", "type": "single stock"},
    "SPY": {"name": "S&P 500 ETF", "category": "fund", "sector": "broad market", "type": "index fund"},
    "QQQ": {"name": "Nasdaq-100 ETF", "category": "fund", "sector": "technology-heavy index", "type": "index fund"},
}

# Common spoken names -> symbol
ALIASES = {
    "BITCOIN": "BTC", "ETHER": "ETH", "ETHEREUM": "ETH", "SOLANA": "SOL",
    "NVIDIA": "NVDA", "APPLE": "AAPL", "MICROSOFT": "MSFT", "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL", "AMAZON": "AMZN", "META": "META", "FACEBOOK": "META",
    "TESLA": "TSLA", "S&P": "SPY", "S&P 500": "SPY", "NASDAQ": "QQQ",
}


def resolve(asset: str | None) -> str | None:
    if not asset:
        return None
    a = asset.strip().upper()
    return ALIASES.get(a, a)


def info(symbol: str | None) -> dict:
    if not symbol:
        return {}
    return {"symbol": symbol, **ASSETS.get(symbol, {"name": symbol, "category": "unknown", "sector": "unknown", "type": "unknown"})}


def tech_like(symbol: str) -> bool:
    return "technology" in ASSETS.get(symbol, {}).get("sector", "")
