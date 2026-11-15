"""Configuration. Everything is overridable from the environment (see .env.example)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

IST = ZoneInfo("Asia/Kolkata")
DATA_DIR = Path(os.environ.get("FINN_DATA_DIR", ROOT / ".finn-cache"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# live   -> Yahoo / NSE / BSE / screener.in
# sample -> a small fictional universe, so the product can be explored offline
DATA_MODE = os.environ.get("FINN_DATA_MODE", "live").lower()

# Mock portfolio: 20 NSE names across sectors and sizes (large -> mid cap).
PORTFOLIO = [
    "RELIANCE", "HDFCBANK", "INFY", "ITC", "LT", "BHARTIARTL", "SUNPHARMA",
    "TITAN", "MARUTI", "BAJFINANCE", "ASIANPAINT", "DMART", "DIXON", "POLYCAB",
    "PERSISTENT", "HAL", "TRENT", "DEEPAKNTR", "IEX", "ASTRAL",
]
# Ad-hoc research suggestions (outside the portfolio). The engine takes any NSE ticker.
RESEARCH_PICKS = ["TCS", "PIDILITIND", "TATASTEEL", "CDSL", "KPITTECH"]

if os.environ.get("FINN_PORTFOLIO"):
    PORTFOLIO = [s.strip().upper() for s in os.environ["FINN_PORTFOLIO"].split(",") if s.strip()]

# Default alert rules. The client can override every one of these per request.
DEFAULT_RULES = {
    "vol": 2.0,        # volume >= vol x average of the previous `lookback` sessions
    "lookback": 20,
    "px": 4.0,         # |daily close-to-close move| >= px %
    "care": ["results", "M&A", "management_change", "fund_raise", "litigation",
             "credit_rating", "pledging"],
    "mute": [],
}

# --- LLM routing (any OpenAI-compatible endpoint) ---------------------------------
PROVIDERS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
LLM_PROVIDER = os.environ.get("FINN_LLM_PROVIDER", "gemini").lower()
LLM_BASE = os.environ.get("FINN_LLM_BASE") or PROVIDERS.get(LLM_PROVIDER, "")
LLM_KEY = os.environ.get("FINN_LLM_KEY", "")
MODEL_CHEAP = os.environ.get("FINN_MODEL_CHEAP", "")    # bulk extraction / classification
MODEL_STRONG = os.environ.get("FINN_MODEL_STRONG", "")  # the one or two reasoning calls


def llm_ready() -> bool:
    return bool(LLM_BASE and MODEL_CHEAP and (LLM_KEY or LLM_PROVIDER == "ollama"))


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
ANN_ORDER = [s for s in os.environ.get("FINN_ANN_ORDER", "nse,bse,screener").split(",") if s]
