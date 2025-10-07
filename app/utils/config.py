import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


@dataclass
class Settings:
    # General
    monitor_target_name: str = os.getenv("MONITOR_TARGET_NAME", "Hurricane Alex")
    monitor_region: str = os.getenv("MONITOR_REGION", "Florida")
    portfolio_csv: str = os.getenv("PORTFOLIO_CSV", "data/portfolio_alpha.csv")
    output_dir: str = os.getenv("OUTPUT_DIR", "output")

    # APIs
    newsapi_key: str | None = os.getenv("NEWSAPI_KEY")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")

    # LLM
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    # Scheduler
    run_interval_minutes: int = int(os.getenv("RUN_INTERVAL_MINUTES", "60"))
    run_once: bool = os.getenv("RUN_ONCE", "0") == "1"

    # Networking
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "20"))
    http_retries: int = int(os.getenv("HTTP_RETRIES", "3"))


settings = Settings()

# Ensure output subdirectories exist
os.makedirs(settings.output_dir, exist_ok=True)
os.makedirs(os.path.join(settings.output_dir, "briefings"), exist_ok=True)
os.makedirs(os.path.join(settings.output_dir, "logs"), exist_ok=True)
