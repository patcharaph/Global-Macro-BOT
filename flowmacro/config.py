from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass
class Settings:
    # Secrets (from .env)
    fred_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    gmail_sender: str = ""
    gmail_app_password: str = ""
    gmail_recipient: str = ""
    openrouter_api_key: str = ""

    # Regime engine
    rolling_window_years: int = 5
    confidence_enter: float = 8.0    # below = TRANSITIONING  (avg |g-50|+|i-50| < 8)
    confidence_exit: float = 12.0   # above = exit TRANSITIONING

    # Portfolio
    cash_buffer_pct: float = 0.20


settings = Settings(
    fred_api_key=os.getenv("FRED_API_KEY", ""),
    supabase_url=os.getenv("SUPABASE_URL", ""),
    supabase_key=os.getenv("SUPABASE_KEY", ""),
    gmail_sender=os.getenv("GMAIL_SENDER", ""),
    gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", ""),
    gmail_recipient=os.getenv("GMAIL_RECIPIENT", ""),
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
)
