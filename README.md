# Research Agent · 推理实验工作台

一个会把性能疑问变成**可复跑对照实验**的研究 Agent：自己检索资料、自己跑真机实验、
自己判断证据够不够，最后交一份带复跑命令的报告。

> 本地 MLX-LM 承担全部实测推理；云端模型只在决策节点被调用，不跑推理。

## 它是怎么分工的

| 角色 | 谁来做 | 说明 |
| --- | --- | --- |
| 实验推理 | **本地** MLX-LM（Qwen3-0.6B-4bit） | 单轮 14 次真实生成，每次 1,520 token 前缀 |
| 检索与抓取 | 本地工具 + 公开接口 | 本地资料集、Tavily（可选）、arXiv/DataCite |
| 规划与判断 | **云端** DeepSeek | 决定下一步、要不要补测、如何写结论；单次运行最多 8 次调用 |
| 证据落盘 | 本地文件 | `search-*.json` / `source-*.json` / `experiment-*.json` |

单次完整研究约 **22 秒**、云端约 **1.1 万 token**，本地推理不计费。

## 快速开始（macOS · Apple Silicon）

```bash
git clone https://github.com/Leemenghao/bohack2026
cd bohack2026
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo 'DEEPSEEK_API_KEY=你的key' > .env
# 可选：开启通用网页检索（不填则只用 arXiv 元数据）
echo 'TAVILY_API_KEY=你的key' >> .env
```

模型权重放在 `models/Qwen3-0.6B-4bit`（已被 `.gitignore` 排除，需自行下载）。

## 跑一次研究

```bash
# 只跑基准，验证 MLX 环境（不调用云端）
python benchmark/prefix_cache.py models/Qwen3-0.6B-4bit --workload shared

# 完整研究：检索 → 假设 → 实测 → 决策 → 报告
python research_agent.py "MLX-LM 的前缀缓存能否降低首 token 延迟？请实测"
```

## 起界面

```bash
python web_server.py --port 8766
# 打开 http://127.0.0.1:8766
```

页面会实时显示：检索来源（带外链）、每轮实验的 TTFT 对照、最终报告与复跑命令。
最近 5 次运行保存在浏览器本地，刷新不丢。

## 运行产物

每次运行在 `runs/<id>/` 下生成：

| 文件 | 内容 |
| --- | --- |
| `report.md` | 结论正文，含资料引用与复跑命令 |
| `summary.json` | 问题、模型、耗时与 token 用量 |
| `experiment-*.json` | 单轮实验的请求级原始记录 |
| `search-*.json` | 一次检索的查询与命中来源 |
| `source-*.json` | 已读取的论文摘要或网页正文 |

## 测试

```bash
python -m unittest discover -s tests -v
```

覆盖本地资料集的排序与匹配规则，不需要网络、不需要 MLX。

## 项目结构

```
web/                     零依赖前端（HTML + CSS + JS，由标准库 HTTP 服务直出）
research_agent.py        Agent 编排、工具注册、报告生成
web_server.py            本地工作台服务
benchmark/prefix_cache.py 真机基准脚本
vendor/deepagents/       内置 Agent 框架（含自研 research/ 子包）
tests/                   检索逻辑的冒烟测试
DESIGN_SYSTEM.md         已实现的设计规范与对比度下限
```

## 已知限制

- `mlx-lm` 只支持 Apple Silicon；其他平台只能跑界面与检索
- 单次只允许一个研究在运行（并发请求返回 409）
- 未验证：超过 2,048 token 的前缀、并发下的缓存淘汰、采样温度对 TTFT 的影响
