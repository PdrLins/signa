"""Back-end version (back-end/VERSION). Bumped on every commit that touches
back-end/ by the repo's pre-commit hook (.githooks/pre-commit). Shown by
GET /api/v1/health and in the web app (Profile → About)."""

from pathlib import Path

_FILE = Path(__file__).resolve().parents[2] / "VERSION"

try:
    APP_VERSION = _FILE.read_text().strip() or "0.0.0"
except OSError:
    APP_VERSION = "0.0.0"
