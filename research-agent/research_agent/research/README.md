# LuLu Research Tools

The research harness uses explicit tools and a per-run resource ledger.

| Module | Responsibility |
| --- | --- |
| `sources.py` and `tools.py` | Search, fetch discovered sources, and save text evidence |
| `experiments.py` and `worker.py` | Execute benchmarks with cancellation, timing, and resource records |
| `sandbox.py` | Confine generated Python and numeric candidates with macOS Seatbelt |
| `kernel.py` | Maintain session candidates and evidence-linked lessons |
| `history.py` | Generate metered summaries and read explicitly shared session evidence |
| `decisions.py` | Decide whether to retest, revise, or finish within the remaining budget |
| `ledger.py` | Persist model, tool, experiment, and stage usage in CNY |

Models and search use separate settings. Search and fetch return saved text rather than original PDF files. Generic generated code has no network access, while explicit search tools run in the trusted backend.

Generated-code workers have a 30-second limit. Fixed classification and MLX workers use a 180-second limit. Experiments have no count cap. Three consecutive worker failures stop further execution for that tool.

See the [development guide](../../docs/development.md) for storage, sharing, measurement scope, and execution boundaries.
