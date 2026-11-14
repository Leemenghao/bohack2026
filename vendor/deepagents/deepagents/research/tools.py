"""Search, fetch, and persist evidence for a single research run."""

import json
from uuid import uuid4

import httpx

from deepagents.research.sources import (
    MAX_CONTENT_CHARS,
    MAX_EVIDENCE_CHARS,
    fetch_web_source,
    find_sources,
    search_web,
)


def make_research_tools(run_dir, tavily_key="", on_event=None):
    """Build tools that share only the current run's discovered source IDs."""
    web_sources = {}

    def record_search(query, sources, **metadata):
        data = {"query": query, "sources": sources, **metadata}
        record = run_dir / f"search-{uuid4().hex[:8]}.json"
        record.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        if on_event:
            for source in sources:
                on_event({"type": "source", "query": query, **source})
        return data

    def search_sources(query: str) -> list[dict]:
        """Find relevant excerpts in the local MLX and prefix-caching collection.

        Use specific Chinese or English keywords. Returns source IDs, titles, URLs
        and excerpts. An empty list means the collection has no matching material.
        """
        query = query.strip()[:400]
        return record_search(query, find_sources(query))["sources"]

    def web_search(query: str) -> dict:
        """Discover public sources online. Use short, specific keywords, preferably in English.

        Results are candidates; call fetch_source with a selected source ID to read it.
        """
        query = query.strip()[:400]
        provider = "tavily" if tavily_key else "datacite"
        try:
            sources = search_web(query, tavily_key)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            return record_search(query, [], provider=provider, error=type(error).__name__)
        web_sources.update((source["source_id"], source) for source in sources)
        return record_search(query, sources, provider=provider)

    def fetch_source(source_id: str) -> dict:
        """Read and save a source returned by this run's web_search. Pass the source ID, not a URL."""
        source = web_sources.get(source_id)
        if source is None:
            return {"source_id": source_id, "error": "Choose a source ID from web_search."}
        try:
            kind, content = fetch_web_source(source, tavily_key)
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
