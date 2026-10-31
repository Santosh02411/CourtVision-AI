import pytest

from app.services.cache import DataUnavailable, TTLCache


def test_failed_source_is_backed_off_not_hammered():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("403")

    c = TTLCache(None)
    with pytest.raises(DataUnavailable):
        c.get("k", 0, boom, "src")
    with pytest.raises(DataUnavailable):
        c.get("k", 0, boom, "src")          # inside the back-off window: must not call upstream again
    assert len(calls) == 1


def test_cdn_header_profiles_have_no_origin():
    from app.services.nba_data import CDN_PROFILES
    assert all("Origin" not in p for p in CDN_PROFILES)


def test_gemini_provider_and_fallback(monkeypatch):
    from app.config import Config
    from app.services import ai_analyst as AI

    monkeypatch.setattr(Config, "GEMINI_API_KEY", "test-key"); monkeypatch.setattr(Config, "ANTHROPIC_API_KEY", "")
    a = AI.AIAnalyst(); assert a.provider == "gemini"
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "Short briefing."}]}}]}

    def fake_post(url, **kw):
        seen.update(url=url, headers=kw["headers"]); return R()
    monkeypatch.setattr(AI.requests, "post", fake_post)
    out = a.brief("t", {"title": "X", "bullets": ["fact one"]})
    assert out["generated_by"] == "gemini" and out["text"] == "Short briefing."
    assert "test-key" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "test-key"   # key only in a header

    monkeypatch.setattr(AI.requests, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    out2 = AI.AIAnalyst().brief("t2", {"title": "Y", "bullets": ["fact two"]})
    assert out2["generated_by"] == "rule-based"        # provider failure degrades to the labelled rule-based summary
