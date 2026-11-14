# BoHack 2026 Research Agent

Agent 会检索资料、提出假设、运行本机实验，并生成带引用、原始记录和复跑命令的报告。可研究 MLX 前缀缓存，或比较不平衡表格分类中类别加权带来的召回率和精确率变化。

在仓库根目录用 Python 3.12 和 uv 安装。分类实验使用固定种子生成的合成数据，在 CPU 上运行。

```bash
uv venv --python 3.12
uv pip install -e ./research-agent
```

运行 MLX 实验需要 Apple Silicon Mac。用 `uv pip install mlx-lm==0.32.2` 安装 MLX-LM，并把 Qwen3-0.6B-4bit 的 MLX 权重放到 `models/Qwen3-0.6B-4bit/`。在项目根目录的 `.env` 填入 `DEEPSEEK_API_KEY`。配置 `TAVILY_API_KEY` 可检索网页并抓取正文。未配置 Tavily 时，在线检索使用 DataCite，并可保存 arXiv 论文的公开摘要。

从仓库根目录启动 Web 服务，并打开 `http://127.0.0.1:8766/`。输入研究问题即可开始。涉及分类、类别加权等关键词的问题会运行表格分类实验，其余问题默认使用 MLX 前缀缓存实验。实验预算默认 3 次，可在「运行设置」中改为 1–3 次。

```bash
.venv/bin/python -m research_agent.web_server
```

只查看已有历史时，可以从仓库根目录运行 `python3 web_server.py`。

macOS 上可以用 `bash desktop/build.sh` 生成 `Research Agent.app`，再双击打开独立窗口。构建需要 Xcode Command Line Tools，应用需要放在已安装依赖的仓库根目录。窗口会启动本地后端并加载同一套网页。模型和在线检索仍使用上面的配置。

点击左侧「新建研究」返回提问页，点击历史记录可查看资料、实验和报告。历史保存在本地 `runs/`，重开窗口后可继续查看。退出时尚未完成的研究会显示为「已中断」。

前端通过 `GET /api/runs` 读取 `{"runs": [...]}` 历史列表，通过 `GET /api/runs/<id>` 读取单次研究的事件、状态和报告。报告页可下载整轮产物，包含已保存的时间线、来源和实验数据。

也可以直接从命令行运行。

```bash
.venv/bin/python -m research_agent.cli "MLX 中共享长前缀能否降低首 token 延迟？"
.venv/bin/python -m research_agent.cli --task classification "类别加权能否提高少数类召回率？"
```

云端模型调用默认最多 15 次，可用 CLI 的 `--cloud-budget` 调整。报告会列出调用次数和 token 用量。CLI 可用 `--no-memory` 跳过上一轮研究摘要。

研究代码位于 `research-agent/research_agent/`，测速脚本位于 `benchmark/`，网页资源位于 `web/`。报告、检索记录和实测数据保存到 `runs/<run_id>/`。

项目基于 [LangChain Deep Agents](https://github.com/langchain-ai/deepagents) 修改，并按 [MIT 许可证](LICENSE)发布。
