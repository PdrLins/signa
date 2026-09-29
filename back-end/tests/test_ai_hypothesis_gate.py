"""Unproven hypotheses must not reach Claude's prompt."""

from app.core.config import settings
from app.services.knowledge_service import KnowledgeService


def _block(monkeypatch, entries, min_n=30):
    monkeypatch.setattr(settings, "hypothesis_prompt_min_observations", min_n)
    svc = KnowledgeService.__new__(KnowledgeService)
    monkeypatch.setattr(svc, "get_active_thinking", lambda: entries, raising=False)
    return svc.get_active_thinking_block()


def test_small_sample_hypothesis_hidden(monkeypatch):
    h = {"hypothesis": "Solar wins", "observations_supporting": 4, "observations_contradicting": 1}
    assert _block(monkeypatch, [h]) == ""


def test_well_observed_hypothesis_shown(monkeypatch):
    h = {"hypothesis": "Solar wins", "observations_supporting": 20,
         "observations_contradicting": 8, "observations_neutral": 2}
    assert "Solar wins" in _block(monkeypatch, [h])
