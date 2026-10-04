"""Signa is the portfolio product only: the brain (scans, signals, AI) lives
in Signa Advisor. Guard against it creeping back in."""

import importlib
import pkgutil
import sys

import app

ADVISOR_PACKAGES = ("app.ai", "app.scanners", "app.signals", "app.tools", "app.services.daily_learning")
AI_LIBRARIES = ("anthropic", "openai", "pandas_ta")


def test_no_advisor_packages_or_ai_libraries_are_imported():
    import main  # noqa: F401  (the whole app, every router)

    for m in pkgutil.walk_packages(app.__path__, "app."):
        importlib.import_module(m.name)
    loaded = set(sys.modules)
    assert not {m for m in loaded if m.startswith(ADVISOR_PACKAGES)}
    assert not {m for m in loaded if m.split(".")[0] in AI_LIBRARIES}


def test_requirements_have_no_ai_libraries():
    from pathlib import Path

    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().lower()
    for lib in ("anthropic", "openai", "pandas-ta", "pandas_ta"):
        assert lib not in req
