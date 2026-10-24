"""Settings loaded from environment variables / backend/.env."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # live = True Markets quotes and prices only. Orders stay on broker_mode.
    market_mode: Literal["mock", "live"] = "live"
    # mock = fake balances, no orders sent. live = real True Markets orders.
    broker_mode: Literal["mock", "live"] = "mock"

    
    # Tensho wallet server (BROKER_MODE=tensho): trades the Tensho customer's Gateway wallet
    #tensho_url: str = "http://localhost:4747"
    #tensho_email: str = ""
    #tensho_password: str = ""
    #tensho_asset_map: str = "SOL=SOL@solana,BTC=CBBTC@base,ETH=ETH@base"

    # Guardrails
    max_trade_usd: float = 10.0
    daily_limit_usd: float = 40.0
    allowed_assets: str = "BTC,ETH,SOL"
    quote_asset: str = "USDC"
    quote_ttl_seconds: int = 30

    # Open-source LLM (OpenAI-compatible endpoint, e.g. Ollama or vLLM)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_timeout_seconds: float = 20.0

    # SEC EDGAR asks for a User-Agent with a contact email on automated requests.
    sec_user_agent: str = "Talk-to-Trade hackathon demo (set SEC_USER_AGENT to include your email)"

    cors_origins: str = "http://localhost:5173"

    @property
    def allowed_asset_list(self) -> list[str]:
        return [a.strip().upper() for a in self.allowed_assets.split(",") if a.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
