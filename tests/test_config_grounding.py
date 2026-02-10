from isrc101_agent.config import Config


def test_grounding_defaults_present():
    cfg = Config()
    assert cfg.grounded_web_mode == "strict"
    assert cfg.grounded_retry == 1
    assert cfg.grounded_visible_citations == "sources_only"
    assert cfg.grounded_context_chars == 8000


def test_grounding_mode_normalization():
    cfg = Config()
    assert cfg._normalize_grounded_web_mode("on") == "strict"
    assert cfg._normalize_grounded_web_mode("strict") == "strict"
    assert cfg._normalize_grounded_web_mode("off") == "off"
    assert cfg._normalize_grounded_web_mode("unknown") == "strict"


def test_grounding_citation_normalization():
    cfg = Config()
    assert cfg._normalize_grounded_citations("sources_only") == "sources_only"
    assert cfg._normalize_grounded_citations("inline") == "inline"
    assert cfg._normalize_grounded_citations("bad") == "sources_only"
