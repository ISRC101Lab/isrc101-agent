"""Web evidence collection and verification protocol."""

import json
import re
import time
from collections import OrderedDict
from typing import List, Dict, Optional, Tuple

from .url_utils import (
    SEARCH_URL_RE,
    extract_search_links,
    matches_official_domains,
    normalize_text_for_match,
    render_sources_footer,
    render_grounding_refusal,
    render_grounding_partial,
)

__all__ = ["GroundingState"]

_PAYLOAD_RE = re.compile(
    re.escape("<grounding_json>")
    + r"\s*(\{.*?\})\s*"
    + re.escape("</grounding_json>"),
    flags=re.DOTALL,
)


class GroundingState:
    GROUNDED_WEB_MODES = {"off", "strict"}
    GROUNDED_CITATION_MODES = {"sources_only", "inline"}
    GROUNDING_OPEN = "<grounding_json>"
    GROUNDING_CLOSE = "</grounding_json>"
    MAX_WEB_EVIDENCE_DOCS = 24

    def __init__(
        self, *,
        web_mode: str,
        retry: int,
        visible_citations: str,
        context_chars: int,
        search_max_seconds: int,
        search_max_rounds: int,
        search_per_round: int,
        official_domains: List[str],
        fallback_to_open_web: bool,
        partial_on_timeout: bool,
    ):
        self.web_mode = web_mode
        self.retry = retry
        self.visible_citations = visible_citations
        self.context_chars = context_chars
        self.search_max_seconds = search_max_seconds
        self.search_max_rounds = search_max_rounds
        self.search_per_round = search_per_round
        self.official_domains = official_domains
        self.fallback_to_open_web = fallback_to_open_web
        self.partial_on_timeout = partial_on_timeout

        # Per-session state
        self.evidence_store: Dict[str, str] = {}
        self.evidence_normalized_store: Dict[str, str] = {}
        self.evidence_order_map: OrderedDict[str, None] = OrderedDict()

        # Per-turn state
        self.turn_web_used: bool = False
        self.turn_web_sources: set = set()

    @property
    def evidence_order(self) -> List[str]:
        """Backward-compatible list view of evidence URL ordering."""
        return list(self.evidence_order_map.keys())

    def turn_source_urls(self) -> List[str]:
        return [url for url in self.evidence_order_map if url in self.turn_web_sources]

    def should_enforce(self) -> bool:
        return (
            self.web_mode == "strict"
            and self.turn_web_used
            and bool(self.turn_web_sources)
        )

    def reset_turn(self):
        self.turn_web_used = False
        self.turn_web_sources.clear()
        self.evidence_normalized_store.clear()

    def build_context_block(self) -> str:
        sources = self.turn_source_urls()
        if not sources:
            return ""
        remaining = self.context_chars
        blocks: List[str] = []
        for url in sources:
            if remaining <= 0:
                break
            raw = (self.evidence_store.get(url) or "").strip()
            if not raw:
                continue
            take = min(len(raw), remaining)
            excerpt = raw[:take].strip()
            if not excerpt:
                continue
            blocks.append(f"[SOURCE] {url}\n{excerpt}\n[/SOURCE]")
            remaining -= len(excerpt)
        return "\n\n".join(blocks)

    def compose_system_prompt(self, base_system: str, feedback: str = "") -> str:
        if not self.should_enforce():
            return base_system

        sources = self.turn_source_urls()
        evidence_block = self.build_context_block()
        if not sources or not evidence_block:
            return base_system

        source_lines = "\n".join(f"- {url}" for url in sources)
        protocol = (
            "\n\n## Strict web-grounding protocol (mandatory for this turn)\n"
            "- You MUST answer using only the provided SOURCE blocks and this turn's web tool outputs.\n"
            "- Do not use training memory or unstated assumptions.\n"
            "- Return EXACTLY one JSON object wrapped by tags below, and no other text:\n"
            f"  {self.GROUNDING_OPEN}\n"
            '  {"answer":"...","claims":[{"text":"...","source_url":"...","evidence_quote":"..."}],"sources":["..."]}\n'
            f"  {self.GROUNDING_CLOSE}\n"
            "- If evidence is insufficient, return:\n"
            f"  {self.GROUNDING_OPEN}\n"
            '  {"insufficient_evidence":true,"reason":"...","sources":["..."]}\n'
            f"  {self.GROUNDING_CLOSE}\n"
            "- Every claim must include source_url from allowed list and an exact evidence_quote substring from that source.\n"
            "- Allowed source URLs for this turn:\n"
            f"{source_lines}\n"
            "- Evidence documents:\n"
            f"{evidence_block}"
        )

        if feedback:
            protocol += (
                "\n\n## Grounding validation feedback from previous attempt\n"
                f"- {feedback}\n"
                "- Fix the issue and regenerate the tagged JSON payload only.\n"
                "- Use ONLY exact quotes from the SOURCE blocks above as evidence_quote.\n"
                "- If you cannot find an exact substring match in the source, use insufficient_evidence instead of fabricating quotes.\n"
                "- Do NOT paraphrase or reword source text for evidence_quote — copy it verbatim."
            )

        return base_system + protocol

    def parse_payload(self, content: str) -> Optional[dict]:
        m = _PAYLOAD_RE.search(content)
        raw_json = m.group(1) if m else content.strip()
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def quote_exists_in_source(self, quote: str, source_url: str, source_text: str) -> bool:
        q = normalize_text_for_match(quote)
        cache_key = str(source_url or "").strip()
        s = self.evidence_normalized_store.get(cache_key)
        if s is None:
            s = normalize_text_for_match(source_text)
            self.evidence_normalized_store[cache_key] = s
        if not q or not s:
            return False
        return q in s

    def finalize_content(self, raw_content: str) -> Tuple[str, Optional[str]]:
        if not self.should_enforce():
            return raw_content, None

        payload = self.parse_payload(raw_content)
        if payload is None:
            return "", "Missing or invalid grounded JSON payload."

        if payload.get("insufficient_evidence"):
            reason = str(payload.get("reason", "")).strip()
            return render_grounding_refusal(reason, self.turn_source_urls()), None

        answer = str(payload.get("answer", "")).strip()
        if not answer:
            return "", "Grounded payload must include a non-empty answer field."

        claims = payload.get("claims")
        if not isinstance(claims, list) or not claims:
            return "", "Grounded payload must include at least one claim with evidence."

        errors: List[str] = []
        valid_claim_sources: List[str] = []
        for index, claim in enumerate(claims, 1):
            if not isinstance(claim, dict):
                errors.append(f"Claim #{index} is not an object.")
                continue
            claim_text = str(claim.get("text", "")).strip()
            source_url = str(claim.get("source_url", "")).strip()
            evidence_quote = str(claim.get("evidence_quote", "")).strip()
            if not claim_text:
                errors.append(f"Claim #{index} is missing text.")
            if not source_url:
                errors.append(f"Claim #{index} is missing source_url.")
                continue
            if source_url not in self.turn_web_sources:
                errors.append(f"Claim #{index} uses non-turn source URL: {source_url}")
                continue
            source_doc = self.evidence_store.get(source_url, "")
            if not source_doc:
                errors.append(f"Claim #{index} source text is unavailable: {source_url}")
                continue
            if len(evidence_quote) < 8:
                errors.append(f"Claim #{index} evidence_quote is too short.")
                continue
            if not self.quote_exists_in_source(evidence_quote, source_url, source_doc):
                errors.append(f"Claim #{index} evidence_quote not found in source: {source_url}")
                continue
            valid_claim_sources.append(source_url)

        if errors:
            return "", "; ".join(errors)

        sources: List[str] = []
        declared = payload.get("sources")
        if isinstance(declared, list):
            for item in declared:
                url = str(item).strip()
                if url in self.turn_web_sources and url not in sources:
                    sources.append(url)
        for url in valid_claim_sources:
            if url not in sources:
                sources.append(url)

        if not sources:
            sources = self.turn_source_urls()

        rendered = answer
        if self.visible_citations in ("sources_only", "inline"):
            rendered += render_sources_footer(sources)
        return rendered, None

    def extract_url_and_body(self, result: str) -> Tuple[str, str]:
        text = result.strip()
        if not text:
            return "", ""
        lines = text.splitlines()
        if not lines:
            return "", ""
        first = lines[0].strip()
        if first.lower().startswith("url:"):
            url = first[4:].strip()
            body = "\n".join(lines[1:]).strip()
            return url, body
        return "", text

    def record_evidence(self, url: str, text: str):
        clean_url = (url or "").strip()
        if not clean_url.lower().startswith(("http://", "https://")):
            return
        clean_text = (text or "").strip()
        if not clean_text:
            return

        if len(clean_text) > self.context_chars:
            clean_text = clean_text[:self.context_chars] + "\n... (truncated)"

        self.evidence_store[clean_url] = clean_text
        self.evidence_normalized_store.pop(clean_url, None)
        if clean_url in self.evidence_order_map:
            self.evidence_order_map.move_to_end(clean_url)
        else:
            self.evidence_order_map[clean_url] = None

        while len(self.evidence_order_map) > self.MAX_WEB_EVIDENCE_DOCS:
            oldest, _ = self.evidence_order_map.popitem(last=False)
            self.evidence_store.pop(oldest, None)
            self.evidence_normalized_store.pop(oldest, None)

        self.turn_web_used = True
        self.turn_web_sources.add(clean_url)

    def capture_fetch_evidence(self, result: str):
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return
        url, body = self.extract_url_and_body(result)
        if not url:
            return
        self.record_evidence(url, body)

    def capture_search_evidence(self, result: str):
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return

        links = SEARCH_URL_RE.findall(result)
        if not links:
            return

        lines = result.splitlines()
        snippets: Dict[str, List[str]] = {}
        snippet_len: Dict[str, int] = {}
        current_url = ""
        for raw in lines:
            line = raw.rstrip()
            m = SEARCH_URL_RE.search(line)
            if m:
                title = line[:m.start()].strip().lstrip("[").rstrip("]").strip()
                current_url = m.group(1).strip()
                snippets.setdefault(current_url, [])
                snippet_len.setdefault(current_url, 0)
                if title:
                    snippets[current_url].append(title)
                    snippet_len[current_url] += len(title) + 1
                continue

            if not current_url:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("Search:") or stripped.startswith("**Summary:**"):
                continue
            snippets[current_url].append(stripped)
            snippet_len[current_url] += len(stripped) + 1
            if snippet_len[current_url] >= 500:
                current_url = ""

        for url in links:
            snippet_text = "\n".join(snippets.get(url, []))
            if not snippet_text:
                snippet_text = "Search result source (no snippet provided)."
            self.record_evidence(url, snippet_text)

    def supplement_sources(self, user_msg: str, error_hint: str,
                           safe_search_fn, safe_fetch_fn) -> Tuple[int, bool]:
        deadline = time.monotonic() + max(1, self.search_max_seconds)
        rounds = max(1, self.search_max_rounds)
        per_round = max(1, self.search_per_round)
        official_only = bool(self.official_domains)
        use_domains: Optional[List[str]] = list(self.official_domains) if official_only else None
        fetched_count = 0
        timed_out = False
        attempted_fetch_urls: set = set()
        attempted_queries: set = set()

        search_hint = error_hint.strip()[:300]

        # State accumulated across rounds for chain-style search
        discovered_keywords: List[str] = []
        candidate_url_queue: List[str] = []
        _static_suffixes = ["official docs", "documentation", "reference guide",
                            "API reference", "changelog", "tutorial",
                            "troubleshooting", "examples"]

        for round_idx in range(rounds):
            if time.monotonic() >= deadline:
                timed_out = True
                break

            # --- Phase 1/2: build query for this round ---
            query = self._build_chain_query(
                round_idx, user_msg, search_hint,
                discovered_keywords, _static_suffixes, attempted_queries,
            )
            if query is None:
                continue

            attempted_queries.add(query)

            search_result = safe_search_fn(query, max_results=per_round * 3, domains=use_domains)
            self.capture_search_evidence(search_result)

            # --- Extract leads from this round's results ---
            new_kw, new_urls = self._extract_leads(search_result, user_msg)
            for kw in new_kw:
                if kw not in discovered_keywords:
                    discovered_keywords.append(kw)
            for url in new_urls:
                if url not in attempted_fetch_urls and url not in candidate_url_queue:
                    candidate_url_queue.append(url)

            # --- Collect direct links from search result ---
            links = extract_search_links(search_result)
            if use_domains:
                links = [u for u in links if matches_official_domains(u, self.official_domains)]

            for url in links:
                if url not in attempted_fetch_urls and url not in candidate_url_queue:
                    candidate_url_queue.append(url)

            if not candidate_url_queue and official_only and self.fallback_to_open_web:
                official_only = False
                use_domains = None
                continue

            # --- Phase 3: Fetch from candidate queue ---
            fetch_budget = per_round
            while candidate_url_queue and fetch_budget > 0:
                url = candidate_url_queue.pop(0)
                if url in attempted_fetch_urls:
                    continue
                attempted_fetch_urls.add(url)
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                before_text = self.evidence_store.get(url, "")
                fetched = safe_fetch_fn(url)
                self.capture_fetch_evidence(fetched)
                after_text = self.evidence_store.get(url, "")
                if after_text and after_text != before_text:
                    fetched_count += 1
                fetch_budget -= 1

            # Don't exit on first success — accumulate until we have enough depth
            if fetched_count >= per_round * 2:
                break

        return fetched_count, timed_out

    @staticmethod
    def _extract_leads(search_result: str, user_msg: str) -> Tuple[List[str], List[str]]:
        """Extract new keywords and candidate URLs from a search result.

        Returns (new_keywords, candidate_urls).
        - new_keywords: terms appearing >=2 times in snippets but absent from user_msg
        - candidate_urls: ordered list of URLs found in the result
        """
        if not search_result or search_result.startswith(("Web error:", "Error:", "Blocked:")):
            return [], []

        candidate_urls = extract_search_links(search_result)

        # Count word frequencies in the result snippets
        user_lower = user_msg.lower()
        user_words = set(re.findall(r'\b[a-zA-Z][\w.-]{2,}\b', user_lower))
        # Also include common stop words to filter
        stop_words = {
            "the", "and", "for", "with", "from", "this", "that", "have", "are",
            "was", "were", "will", "been", "being", "has", "had", "does", "did",
            "but", "not", "you", "all", "can", "her", "his", "its", "our", "out",
            "too", "use", "how", "may", "new", "one", "two", "see", "way", "who",
            "get", "got", "let", "say", "she", "why", "try", "ask", "own", "also",
            "into", "over", "such", "than", "them", "then", "what", "when", "here",
            "more", "some", "very", "about", "which", "would", "there", "their",
            "other", "could", "after", "using", "these", "those", "should", "https",
            "http", "www", "com", "org", "html", "docs", "page", "result",
            "search", "found", "results", "official", "documentation",
        }

        word_counts: Dict[str, int] = {}
        for word in re.findall(r'\b[a-zA-Z][\w.-]{2,}\b', search_result.lower()):
            if word in user_words or word in stop_words:
                continue
            word_counts[word] = word_counts.get(word, 0) + 1

        # Words appearing >= 2 times, sorted by frequency (descending)
        new_keywords = [
            word for word, count in sorted(word_counts.items(), key=lambda x: -x[1])
            if count >= 2
        ][:10]  # Cap at 10 keywords

        return new_keywords, candidate_urls

    @staticmethod
    def _build_chain_query(
        round_idx: int,
        user_msg: str,
        search_hint: str,
        discovered_keywords: List[str],
        static_suffixes: List[str],
        attempted_queries: set,
    ) -> Optional[str]:
        """Build a search query that evolves across rounds.

        Round 0: user_msg + error_hint + "official docs"
        Round 1: user_msg + "documentation"
        Round 2+: user_msg + discovered keywords subset (chain queries)
        Falls back to static suffixes when keywords are exhausted.
        """
        query_parts = [user_msg.strip()]

        if round_idx == 0:
            if search_hint:
                query_parts.append(search_hint)
            query_parts.append("official docs")
        elif round_idx == 1:
            query_parts.append("documentation")
        else:
            # Phase 2: use discovered keywords for deeper drilling
            # Pick a window of keywords based on round index
            kw_start = (round_idx - 2) * 2
            kw_slice = discovered_keywords[kw_start:kw_start + 3]
            if kw_slice:
                query_parts.append(" ".join(kw_slice))
            else:
                # Keywords exhausted — fall back to static suffixes
                suffix_idx = round_idx - 2 - (len(discovered_keywords) + 1) // 2
                if 0 <= suffix_idx < len(static_suffixes):
                    query_parts.append(static_suffixes[suffix_idx])
                else:
                    # All suffixes exhausted too
                    return None

        query = " ".join(part for part in query_parts if part)
        if query in attempted_queries:
            return None
        return query

    def render_partial(self, reason: str) -> str:
        return render_grounding_partial(reason, self.turn_source_urls())
