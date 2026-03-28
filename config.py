import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def as_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

def as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    trading_mode: str = os.getenv("TRADING_MODE", "paper")

    forex_execution_broker: str = os.getenv("FOREX_EXECUTION_BROKER", "oanda")
    stock_execution_broker: str = os.getenv("STOCK_EXECUTION_BROKER", "alpaca")
    crypto_execution_broker: str = os.getenv("CRYPTO_EXECUTION_BROKER", "alpaca")

    max_risk_per_trade_pct: float = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.005"))
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.02"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
    default_order_size_usd: float = float(os.getenv("DEFAULT_ORDER_SIZE_USD", "1000"))
    kill_switch: bool = as_bool("KILL_SWITCH", False)

    stock_symbols: list[str] = None
    forex_symbols: list[str] = None
    crypto_symbols: list[str] = None

    poll_seconds: int = max(15, int(os.getenv("POLL_SECONDS", "30")))
    polygon_api_key: str = os.getenv("POLYGON_API_KEY", "")

    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_api_secret: str = os.getenv("ALPACA_API_SECRET", "")
    alpaca_base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    alpaca_data_base_url: str = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")

    oanda_api_key: str = os.getenv("OANDA_API_KEY", "")
    oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_env: str = os.getenv("OANDA_ENV", "practice").lower()

    def __post_init__(self):
        object.__setattr__(self, "stock_symbols", as_list("STOCK_SYMBOLS", "AAPL,NVDA,TSLA,AMD,META,MSFT"))
        object.__setattr__(self, "forex_symbols", as_list("FOREX_SYMBOLS", "EUR_USD,GBP_USD,USD_JPY"))
        object.__setattr__(self, "crypto_symbols", as_list("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD,SOL/USD"))

settings = Settings()
