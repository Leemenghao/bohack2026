"""Search, fetch, and persist evidence for a single research run."""

import json
from uuid import uuid4

import httpx

from research_agent.research.sources import (
    MAX_CONTENT_CHARS,
    MAX_EVIDENCE_CHARS,
    DEEPSEEK,
    fetch_web_source,
    find_sources,
    search_web,
)


def make_research_tools(run_dir, deepseek_key="", on_event=None, *, ledger=None, base_url=DEEPSEEK):
    """Build tools that share only the current run's discovered source IDs."""
    web_sources = {}

    def record_search(query, sources, **metadata):
        data = {"query": query, "sources": sources, **metadata}
        record = run_dir / f"search-{uuid4().hex[:8]}.json"
        record.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        if on_event:
            on_event({
                "type": "search", "query": query, "count": len(sources),
                "provider": metadata.get("provider", "local"), "artifact": record.name,
                "error": metadata.get("error"),
            })
            for source in sources:
                on_event({"type": "source", "query": query, **source})
        return data

    def search_sources(query: str) -> list[dict]:
        """Find relevant excerpts in the local MLX and prefix-caching collection.

        Use specific Chinese or English keywords. Returns source IDs, titles, URLs
        and excerpts. An empty list means the collection has no matching material.
        """
        query = query.strip()[:400]
        identifier = ledger.start("local_search", query=query, estimated_cost_cny=0) if ledger else None
        try:
            return record_search(query, find_sources(query))["sources"]
        finally:
            if ledger:
                ledger.finish(identifier)

    def web_search(query: str) -> dict:
        """Discover public sources online. Use short, specific keywords, preferably in English.

        Results are candidates; call fetch_source with a selected source ID to read it.
        """
        query = query.strip()[:128]
        provider = "deepseek" if deepseek_key else "datacite"
        try:
            sources = search_web(query, deepseek_key, ledger, base_url)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            return record_search(query, [], provider=provider, error=type(error).__name__)
        web_sources.update((source["source_id"], source) for source in sources)
        return record_search(query, sources, provider=provider)

    def fetch_source(source_id: str) -> dict:
        """Read and save a source returned by this run's web_search. Pass the source ID, not a URL."""
        source = web_sources.get(source_id)
        if source is None:
            if ledger:
                identifier = ledger.start("tool", name="fetch_source", source_id=source_id, estimated_cost_cny=0)
                ledger.finish(identifier, "rejected", error="unknown_source_id")
            return {"source_id": source_id, "error": "Choose a source ID from web_search."}
        try:
            kind, content = fetch_web_source(source, deepseek_key, ledger, base_url)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            return {"source_id": source_id, "error": type(error).__name__}
        if not content:
            return {"source_id": source_id, "error": "No readable content was returned."}

        record = run_dir / f"source-{uuid4().hex[:8]}.json"
        evidence = {
            **source,
            "content_kind": kind,
            "artifact": record.name,
            "truncated": len(content) > MAX_CONTENT_CHARS,
        }
        record.write_text(json.dumps({**evidence, "content": content[:MAX_CONTENT_CHARS]},
                                     ensure_ascii=False, indent=2))
        if on_event:
            on_event({"type": "source_fetched", **evidence})
        return {**evidence, "content_preview": content[:MAX_EVIDENCE_CHARS]}

    return search_sources, web_search, fetch_source
