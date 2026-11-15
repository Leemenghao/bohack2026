"""Build a relocatable Apple Silicon app and a drag-to-install DMG."""
import hashlib
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "desktop" / "dist"


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Build on Apple Silicon using the project Python 3.12 environment.")
    base = Path(sys.base_prefix).resolve()
    managed = Path(subprocess.check_output(["uv", "python", "dir"], text=True).strip()).resolve()
    if not base.is_relative_to(managed) or Path(sys.prefix).resolve() != ROOT / ".venv":
        raise SystemExit("Use .venv/bin/python with a uv-managed Python 3.12 runtime.")
    packages = Path(sysconfig.get_path("purelib"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".env", ".env.*",
                                    "__editable__*", "_virtualenv.*", "direct_url.json")
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".package-", dir=DIST) as temporary:
        volume = Path(temporary)
        app = volume / "LuLu Research.app"
        subprocess.run(["bash", str(ROOT / "desktop/build.sh"), str(app)], check=True)
        resources = app / "Contents/Resources"
        runtime = resources / "runtime"
        shutil.copytree(base, runtime, symlinks=True, ignore=ignore)
        shutil.copytree(packages, runtime / "lib/python3.12/site-packages",
                        dirs_exist_ok=True, symlinks=True, ignore=ignore)
        project = resources / "project"
        shutil.copytree(ROOT / "research-agent/research_agent", project / "research-agent/research_agent", ignore=ignore)
        shutil.copytree(ROOT / "web", project / "web", ignore=ignore)
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE")

        # A copied environment must not silently import from the developer checkout.
        for path in app.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(app.resolve()):
                raise RuntimeError(f"External symlink in app: {path.relative_to(app)}")
        (volume / "Applications").symlink_to("/Applications")
        (volume / "安装说明.txt").write_text(
            "LuLu Research 0.1.0\n\n"
            "适用 Apple Silicon Mac 与 macOS 26 或更新版本。\n"
            "将 LuLu Research.app 拖入 Applications，然后从应用程序中打开。\n"
            "Python 与运行依赖已内置，无需安装 uv 或保留源码仓库。\n"
            "首次使用请在设置中配置模型和检索服务。密钥存入 macOS 钥匙串。\n"
            "研究数据保存到 ~/Library/Application Support/LuLu Research/data/。\n"
            "安装包不包含 API Key、会话历史和模型权重。CPU 实验无需权重。\n"
            "MLX 实验需将 Qwen3-0.6B-4bit 权重放入上述数据目录的 models/。\n"
            "当前为本地 ad-hoc 签名构建，未做 Apple 开发者签名与公证。\n"
        )
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        # Confirm that the embedded interpreter resolves both app code and compiled dependencies.
        environment = {"PATH": "/usr/bin:/bin", "HOME": temporary, "PYTHONNOUSERSITE": "1",
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(project / "research-agent"),
                       "LULU_DATA_ROOT": str(volume / "probe-data")}
        subprocess.run([str(runtime / "bin/python3"), "-c",
                        "import numpy, sklearn, mlx.core, research_agent.web_server; print('Bundled imports OK')"],
                       cwd=temporary, env=environment, check=True)
        # The import probe must not become part of the distributed volume.
        shutil.rmtree(volume / "probe-data", ignore_errors=True)
        image = DIST / "LuLu-Research-0.1.0-macOS-arm64.dmg"
        subprocess.run(["hdiutil", "create", "-ov", "-volname", "LuLu Research", "-srcfolder", str(volume),
                        "-format", "UDZO", str(image)], check=True)
        destination = DIST / app.name
        if destination.exists():
            shutil.rmtree(destination)
        app.rename(destination)
        with image.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        image.with_suffix(".dmg.sha256").write_text(f"{checksum}  {image.name}\n")
        print(f"Installer: {image}")
        print(f"SHA256: {checksum}")


if __name__ == "__main__":
    main()
