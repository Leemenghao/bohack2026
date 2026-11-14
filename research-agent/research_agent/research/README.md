# BoHack Research Tools

- `sources.py` stores the local source list and implements the online providers.
- `tools.py` exposes `search_sources`, `web_search`, and `fetch_source` to the agent. A tool can fetch only a source discovered during the current run.

By default, online searches use DataCite to find arXiv records and retrieve public abstracts without an API key. Set `TAVILY_API_KEY` in the project root `.env` to search the general web and extract page text through Tavily. Tavily calls use your account's credits.

Search records and fetched content are saved as `search-*.json` and `source-*.json` under `runs/<run_id>/`. This version saves text, not original PDF files.
