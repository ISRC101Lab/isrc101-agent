import json

from isrc101_agent.agent import Agent


class DummyPresetGit:
    available = False


class DummyTools:
    mode = "agent"
    git = DummyPresetGit()
    schemas = []

    def __init__(self):
        self.web_enabled = True
        self.search_calls = 0
        self.fetch_calls = 0
        self._search_result = "Search: q\n\n1. [Doc](https://docs.example.com/ptx91)\n"
        self._fetch_result = "URL: https://docs.example.com/ptx91\n\nPTX ISA 9.1 introduces mbarrier and redux.sync."

    def can_parallelize(self, _name):
        return True

    def execute(self, name, arguments):
        if name == "web_search":
            self.search_calls += 1
            return self._search_result
        if name == "web_fetch":
            self.fetch_calls += 1
            return self._fetch_result
        raise AssertionError(f"unexpected tool: {name}")


class DummyLLM:
    model = "openai/gpt-4o-mini"
    max_tokens = 1024
    context_window = 32000


def _make_agent(*, tools=None, grounded_partial_on_timeout=True) -> Agent:
    return Agent(
        llm=DummyLLM(),
        tools=tools or DummyTools(),
        grounded_web_mode="strict",
        grounded_retry=0,
        grounded_visible_citations="sources_only",
        grounded_context_chars=8000,
        grounded_search_max_seconds=30,
        grounded_search_max_rounds=2,
        grounded_search_per_round=1,
        grounded_official_domains=["docs.example.com"],
        grounded_fallback_to_open_web=True,
        grounded_partial_on_timeout=grounded_partial_on_timeout,
        web_display="brief",
    )


def test_quote_exists_uses_url_keyed_cache():
    agent = _make_agent()
    source_url = "https://docs.example.com/ptx91"
    source_doc = "PTX ISA 9.1 introduces mbarrier and redux.sync."

    assert agent._quote_exists_in_source("mbarrier and redux.sync", source_url, source_doc)
    assert source_url in agent._web_evidence_normalized_store


def test_supplement_grounding_sources_fetches_official_doc():
    tools = DummyTools()
    agent = _make_agent(tools=tools)

    fetched, timed_out = agent._supplement_grounding_sources(
        "latest PTX ISA version", "evidence_quote not found"
    )

    assert timed_out is False
    assert fetched >= 1
    assert tools.search_calls >= 1
    assert tools.fetch_calls >= 1
    assert "https://docs.example.com/ptx91" in agent._turn_web_sources


def test_grounding_partial_render_contains_sources():
    agent = _make_agent()
    agent._record_web_evidence("https://docs.example.com/ptx91", "partial content")

    rendered = agent._render_grounding_partial("timeout while collecting more evidence")

    assert "partial evidence" in rendered
    assert "timeout while collecting more evidence" in rendered
    assert "https://docs.example.com/ptx91" in rendered


def test_finalize_grounding_still_valid_after_optimizations():
    agent = _make_agent()
    source = "https://docs.example.com/ptx91"
    agent._record_web_evidence(source, "PTX ISA 9.1 introduces mbarrier and redux.sync.")

    payload = {
        "answer": "最新版本是 PTX ISA 9.1。",
        "claims": [
            {
                "text": "PTX ISA 9.1 introduces mbarrier.",
                "source_url": source,
                "evidence_quote": "PTX ISA 9.1 introduces mbarrier",
            }
        ],
        "sources": [source],
    }
    content = f"{agent.GROUNDING_OPEN}\n{json.dumps(payload, ensure_ascii=False)}\n{agent.GROUNDING_CLOSE}"

    rendered, err = agent._finalize_assistant_content(content)

    assert err is None
    assert "PTX ISA 9.1" in rendered
    assert source in rendered
