from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "yababy.db"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

DEFAULT_TIMEZONE = "Europe/Moscow"
PIN_TTL_SECONDS = 600
