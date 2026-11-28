import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parents[2]


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://queprint:queprint@localhost:5432/queprint")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",") if o.strip()]
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@queprint.app")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Shop Admin")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", ROOT / "backend" / "storage"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))
CLAMSCAN = _bool("CLAMSCAN")

PRINTER_MODE = os.getenv("PRINTER_MODE", "simulate")  # simulate | cups
PRINTER_NAME = os.getenv("PRINTER_NAME", "")
MAX_ACTIVE_PRINTING = int(os.getenv("MAX_ACTIVE_PRINTING", "3"))
DISPATCH_INTERVAL = int(os.getenv("DISPATCH_INTERVAL", "5"))

MIN_PICKUP_MINUTES = int(os.getenv("MIN_PICKUP_MINUTES", "30"))
SHOP_NAME = os.getenv("SHOP_NAME", "QuePrint")
FRONTEND_DIR = ROOT / "frontend"
