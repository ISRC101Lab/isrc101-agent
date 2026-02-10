import json

from isrc101_agent.agent import Agent


class DummyPresetGit:
    available = False


class DummyTools:
    mode = "agent"
    git = DummyPresetGit()
    schemas = []

    def __init__(self):
        pass


class DummyLLM:
    model = "openai/gpt-4o-mini"
    max_tokens = 4096
    context_window = 128000

    def chat(self, messages, tools=None):
        raise AssertionError("chat should not be called in these unit tests")


def _make_agent() -> Agent:
    return Agent(
        llm=DummyLLM(),
        tools=DummyTools(),
        grounded_web_mode="strict",
        grounded_retry=1,
        grounded_visible_citations="sources_only",
        grounded_context_chars=8000,
        web_display="brief",
    )


def test_capture_web_fetch_stores_evidence_even_brief_mode():
    agent = _make_agent()

    raw = (
        "URL: https://example.com/doc\n\n"
        "alpha beta gamma\n"
        "delta epsilon zeta\n"
    )
    agent._capture_web_fetch_evidence(raw)

    assert "https://example.com/doc" in agent._web_evidence_store
    assert "alpha beta gamma" in agent._web_evidence_store["https://example.com/doc"]
    assert agent._turn_web_used is True
    assert "https://example.com/doc" in agent._turn_web_sources


def test_grounding_accepts_valid_payload_and_adds_sources_footer():
    agent = _make_agent()
    source = "https://docs.example.com/ptx91"
    doc = "PTX ISA 9.1 introduces CUDA Tile programming and mbarrier support."
    agent._record_web_evidence(source, doc)

    payload = {
        "answer": "最新版本是 PTX ISA 9.1。",
        "claims": [
            {
                "text": "PTX ISA 9.1 introduces CUDA Tile programming.",
                "source_url": source,
                "evidence_quote": "PTX ISA 9.1 introduces CUDA Tile programming",
            }
        ],
        "sources": [source],
    }
    content = f"{agent.GROUNDING_OPEN}\n{json.dumps(payload, ensure_ascii=False)}\n{agent.GROUNDING_CLOSE}"

    rendered, err = agent._finalize_assistant_content(content)

    assert err is None
    assert "最新版本是 PTX ISA 9.1" in rendered
    assert "Sources:" in rendered
    assert source in rendered


def test_grounding_rejects_quote_not_in_source():
    agent = _make_agent()
    source = "https://docs.example.com/ptx91"
    agent._record_web_evidence(source, "PTX ISA 9.1 introduces mbarrier.")

    payload = {
        "answer": "PTX 9.1 has redux.sync.",
        "claims": [
            {
                "text": "PTX 9.1 has redux.sync.",
                "source_url": source,
                "evidence_quote": "redux.sync instruction appears",
            }
        ],
        "sources": [source],
    }
    content = f"{agent.GROUNDING_OPEN}\n{json.dumps(payload, ensure_ascii=False)}\n{agent.GROUNDING_CLOSE}"

    rendered, err = agent._finalize_assistant_content(content)

    assert rendered == ""
    assert err is not None
    assert "evidence_quote not found in source" in err


def test_grounding_rejects_non_turn_source_url():
    agent = _make_agent()
    agent._record_web_evidence("https://docs.example.com/ptx91", "PTX 9.1 text")

    payload = {
        "answer": "Answer",
        "claims": [
            {
                "text": "Claim",
                "source_url": "https://other.example.com/not-in-turn",
                "evidence_quote": "Claim quote",
            }
        ],
        "sources": ["https://other.example.com/not-in-turn"],
    }
    content = f"{agent.GROUNDING_OPEN}\n{json.dumps(payload, ensure_ascii=False)}\n{agent.GROUNDING_CLOSE}"

    rendered, err = agent._finalize_assistant_content(content)

    assert rendered == ""
    assert err is not None
    assert "non-turn source URL" in err


def test_grounding_insufficient_evidence_payload_returns_refusal():
    agent = _make_agent()
    source = "https://example.com/a"
    agent._record_web_evidence(source, "doc text")

    payload = {
        "insufficient_evidence": True,
        "reason": "No explicit version in source",
        "sources": [source],
    }
    content = f"{agent.GROUNDING_OPEN}\n{json.dumps(payload, ensure_ascii=False)}\n{agent.GROUNDING_CLOSE}"

    rendered, err = agent._finalize_assistant_content(content)

    assert err is None
    assert "cannot verify" in rendered
    assert "No explicit version in source" in rendered
    assert source in rendered
