# LuLu 开发与配置

[返回项目首页](../../README.md)

## 连接与密钥

模型服务使用 OpenAI 兼容的 Chat Completions 接口，需要支持工具调用。搜索服务独立使用 DeepSeek Search / Fetch 协议，并不是所有模型中转站都提供这组接口。

在设置页填写 Base URL、模型 ID 与 API Key。AI Ping 预设使用 `https://aiping.cn/api/v1`，模型 ID 按服务商实际提供的名称填写。配置只在下一轮开始时生效，正在运行的研究保留启动时快照。

连接元数据位于 `~/Library/Application Support/LuLu Research/settings.json`。密钥通过 keyring 写入 macOS 钥匙串，按服务类别和完整端点绑定。接口不返回密钥，更换地址不会将原密钥发送到新地址。

未保存配置时，默认从项目 `.env` 读取 `DEEPSEEK_API_KEY`。AI Ping 预设只在匹配的地址读取 `AIPING_API_KEY`。保存时可以将对应环境密钥转存钥匙串，原 `.env` 不会自动删除。确认连接正常后可自行移除明文副本。不要提交 `.env`。

## 环境与实验

推荐 Python 3.12。主 Python 环境位于项目 `.venv/`，默认复用依赖，不为每轮复制环境或模型权重。

CPU 算子优化与分类实验无需本地大模型。MLX 实验需要 Apple Silicon，安装附加依赖并准备 `models/Qwen3-0.6B-4bit/` 权重。

```bash
uv pip install mlx-lm==0.32.2
```

网页根据问题关键词选择固定场景。分类与类别加权问题使用分类实验，算子、归一化和 kernel 问题进入算子优化，其余默认 MLX 缓存。当前不是任意任务的自动 benchmark 发现器。

完整服务可通过模块入口或 Web 包装入口启动，两者行为相同。

```bash
.venv/bin/python -m research_agent.web_server
.venv/bin/python web/serve.py
```

CLI 保留用于调试和复现。通过帮助查看任务、预算和 baseline 参数。

```bash
.venv/bin/python -m research_agent.cli --help
```

## 资源账本

所有金额按人民币记录。模型与检索分别计量，每条记录保存用途、耗时、token 或请求数、计费状态与估算费用。自动会话摘要同样是模型调用，用途记为 `session_summary`。

DeepSeek 官方连接使用代码内带版本的参考价格，不自动追踪实时刊例价。第三方连接需要填写输入、输出和缓存命中的每百万 token 单价。未配置单价的调用标为费用未知，汇总只包含已知部分。自定义检索端点也不会套用官方单价。

人民币阈值在下一步动作开始前检查，已发出的请求仍会结算，因此不是预扣款式硬上限。还保留云端调用保护、搜索与抓取次数保护。实验不设固定次数上限，单次执行超时或连续三次失败会停止异常循环。

用量页按轮次展示模型、检索与每次实验。CPU 时间包含工作进程与已回收的子进程，内存是最大单进程高水位，不是并发进程树总内存。强制终止后未返回的数据标为未计量，不推算电费、GPU 时间或硬件折旧。

## 会话、摘要与权限

SQLite 索引在 `runs/conversations.sqlite3`，首次启动会导入旧记录。每个会话以首轮 ID 为标识，共享工作区在 `runs/<session_id>/workspace/`。各轮报告、候选代码与实验快照仍保存在 `runs/<run_id>/`。

Agent 在成功轮次结束后，若调用次数和费用允许，会生成目标、结果、限制、经验与待办摘要。摘要带生成模型、来源轮次和更新时间，写入 `session-summary.json` 并更新 SQLite。生成失败或预算不足不会丢弃原有报告。右键会话可以手动生成或更新摘要，这会新增一个计费轮次。

共享默认关闭。开启后，其他会话通过 `search_research_history` 搜索最多五条摘要，再通过 `read_research_history` 只读查看轮次索引和允许的证据文件。每次读取重新检查权限，禁止越界路径和符号链接。归档会话不参与共享。关闭共享只阻止后续读取，不撤回已进入其他会话的内容。

摘要与经验均由模型生成，未经人工审核。历史内容作为资料处理，不能覆盖当前指令，历史结果不能冒充本轮实测。

## 生成代码的执行边界

`benchmark_python` 和 `benchmark_kernel` 通过 macOS Seatbelt 执行，禁止网络。只读开放 Python 运行时、项目后端代码、当前轮次和会话工作区。只允许向会话工作区与本次结果文件写入。工作进程使用独立环境变量，不继承 API Key，也不能读取宿主钥匙串。

每次执行的墙钟与 CPU 上限为 30 秒，单文件大小限制为 8 MiB。它没有总磁盘配额或完整内存配额，不应当被视为能承载任意不可信软件的虚拟机。macOS 沙箱不可用时拒绝运行生成代码，不回退到无约束执行。

算子工具额外限制 NumPy 数值 API，并用固定 benchmark 验证正确性。一般 Python 工具的输出是脚本陈述，不具有同等的独立验证含义。固定分类和 MLX 工具属于可信后端，仍在宿主执行。

新实验附带沙箱复跑命令。使用记录中的真实 ID 从仓库根目录执行，复跑产物保存为新的 replay 文件，不覆盖原始证据。

```text
.venv/bin/python -m research_agent.research.sandbox RUN_ID EXPERIMENT_ID
```

SSH、远程执行与同步尚未接入。后续执行器应沿用相同的产物、取消和资源记账契约，并显式指定远端工作区与共享范围。

## 代码与协作

源码只放在 `web/`、`desktop/` 和 `research-agent/`。后端入口是 `research_agent.web_server` 和 `research_agent.cli`，benchmark 是包内模块。根目录保留项目说明、依赖入口和许可证。

小功能使用独立提交，开发分支通过 PR 合入 main。提交前检查差异，避免将 `.env`、模型权重、运行历史和虚拟环境加入版本控制。

```bash
.venv/bin/python -m unittest discover -s research-agent/tests
node --check web/app.js
node --check web/artifacts.js
node --check web/sessions.js
git diff --check
```

测试覆盖权限共享与撤销、沙箱越界读写和网络、实验记录、费用与取消等。macOS 沙箱集成测试只在 macOS 执行。修改页面后检查浅色与深色布局，修改后端后重启应用。只有改动 Swift、图标或应用配置时才需要重新构建桌面壳。

## 安装版的数据目录

独立 DMG 的构建与验证见 [桌面构建说明](../../desktop/README.md)。安装版通过 `LULU_DATA_ROOT` 将研究数据放到用户 Application Support 目录，网页和后端从应用包只读加载。开发版未设置该变量时继续使用项目目录。复跑命令会携带安装版的解释器、包路径和数据目录，并对含空格的路径进行引用处理。
