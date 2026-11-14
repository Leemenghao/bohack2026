# BoHack Research Tools

- `sources.py` stores the local source list and implements the online providers.
- `tools.py` exposes `search_sources`, `web_search`, and `fetch_source` to the agent. A tool can fetch only a source discovered during the current run.

The app uses DeepSeek Search/Fetch with `DEEPSEEK_API_KEY`. `sources.py` also retains a DataCite metadata fallback for direct use without a key. Search/fetch billing is recorded separately from model tokens in CNY.

`ledger.py` records model callbacks, tool usage and per-stage costs in `resources.json`. `experiments.py` runs benchmarks through `worker.py` in cancellable process groups, recording CPU time and single-process peak RSS. Local experiments have no count cap, a 180-second timeout and a three-consecutive-failure stop.

Search records and fetched content are saved as `search-*.json` and `source-*.json` under `runs/<run_id>/`. This version saves text, not original PDF files.
