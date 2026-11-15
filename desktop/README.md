# LuLu 桌面构建

[返回项目首页](../README.md)

## 开发窗口

```bash
bash desktop/build.sh
```

在仓库根目录生成 LuLu Research.app，使用项目 `.venv` 和 `runs/`。适合本机开发，不能单独复制到其他电脑使用。

## 独立安装包

在 Apple Silicon Mac 上，使用 uv 管理的 Python 3.12 创建项目环境并安装依赖。构建还需要 Xcode Command Line Tools。当前完整环境中的 MLX 依赖要求 macOS 26 或更新版本。

```bash
.venv/bin/python desktop/package.py
```

输出到 `desktop/dist/`，该目录不提交到 Git。

| 文件 | 用途 |
| --- | --- |
| `LuLu-Research-0.1.0-macOS-arm64.dmg` | 拖入 Applications 安装 |
| `LuLu Research.app` | 内置 Python 的独立应用 |
| `LuLu-Research-0.1.0-macOS-arm64.dmg.sha256` | 安装包校验值 |

构建会复制当前项目环境的运行依赖和许可证，去除 editable 安装路径。安装包包含网页、后端、Python 与运行依赖，不包含项目 `.env`、运行历史或模型权重。打包前应使用只安装项目依赖的环境。

安装后在设置页配置模型与检索服务。密钥保存在 macOS 钥匙串，连接配置位于 `~/Library/Application Support/LuLu Research/settings.json`。

安装版的工作目录为 `~/Library/Application Support/LuLu Research/data/`，会话记录存入其中的 `runs/`。原开发目录的历史保留不变，不自动复制到安装版。

CPU 算子与分类实验无需下载权重。MLX 缓存实验需要将 Qwen3-0.6B-4bit 的权重放到数据目录下的 `models/Qwen3-0.6B-4bit/`。

当前生成的是本地 ad-hoc 签名构建，未做 Developer ID 签名与 Apple 公证。正式对外分发时需要相应开发者凭据与签名流程。

## 验证

构建脚本会检查外部软链接、验证代码签名，并用内置解释器导入应用和编译依赖。

安装包还应在仓库以外的位置验证以下流程。

- 打开桌面窗口并进入设置页
- 用内置 Python 运行算子验证、沙箱分析与分类实验
- 在含空格的数据目录执行保存的复跑命令
- 确认记录写入用户数据目录，不写入应用包
- 确认安装包没有带入密钥和开发会话

## Windows 范围

当前不能直接构建 Windows 安装包。网页可以复用，但桌面窗口基于 AppKit，凭据存储使用 macOS 钥匙串，生成代码使用 Seatbelt，资源统计和进程取消使用 Unix 接口。

Windows 版需要替换桌面壳、接入系统凭据存储、适配进程树取消和资源统计，并提供 Windows 可用的隔离执行器。MLX 实验不能沿用，CPU 分类与数值实验可以作为首批场景。

完成适配后，应在 Windows 本机或 Windows CI 上构建并验证安装包。当前没有生成或验证 `.exe`。
