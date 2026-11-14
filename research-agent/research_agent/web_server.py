import argparse
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit
from uuid import uuid4

from archive import build_archive
from runview import HISTORY_FIELDS, RUN_ID, load_run, save_run, timestamp

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK = "prefix_cache"

ASSETS = {
    "/": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
runs = {}
state_lock = Lock()


def execute(run_id, question, budget, task, cloud_budget):
    def on_event(event):
        with state_lock:
            runs[run_id]["events"].append(event)
            save_run(ROOT / "runs" / run_id, runs[run_id])

    try:
        from research_agent.cli import run_research

        run_research(question, ROOT / "runs" / run_id, budget, on_event, task=task, cloud_budget=cloud_budget)
    except ModuleNotFoundError as error:
        update = {"status": "failed", "error": f"本机缺少运行依赖（{error.name}）。请按 README 安装。"}
    except Exception as error:
        # Provider errors can contain request metadata. Expose only the status or class.
        status = getattr(error, "status_code", None)
        detail = f"HTTP {status}" if isinstance(status, int) else type(error).__name__
        update = {"status": "failed", "error": f"研究运行失败（{detail}）。请检查模型配置或本地实验环境。"}
    else:
        update = {"status": "complete"}
    with state_lock:
        runs[run_id].update(update)
        save_run(ROOT / "runs" / run_id, runs[run_id])
        del runs[run_id]


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_data(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def is_local_request(self):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        return host in hosts and self.headers.get("Origin") in (None, f"http://{host}")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_data(200, (ROOT / "web" / filename).read_bytes(), content_type)
            return

        if path.startswith("/api/") and not self.is_local_request():
            self.send_json(403, {"error": "请从本地工作台查看研究记录。"})
            return

        if path == "/api/runs":
            with state_lock:
                history = []
                for folder in (ROOT / "runs").glob("*"):
                    if folder.is_dir() and RUN_ID.fullmatch(folder.name):
                        run = runs.get(folder.name) or load_run(folder)
                        if run:
                            history.append({"id": folder.name, **{key: run[key] for key in HISTORY_FIELDS}})
            self.send_json(200, {"runs": sorted(history, key=lambda run: run["created_at"], reverse=True)})
            return

        export_match = re.fullmatch(r"/api/runs/([a-f0-9]{12})/export", path)
        if export_match:
            run_id = export_match.group(1)
            try:
                payload = build_archive(ROOT / "runs" / run_id, run_id)
            except FileNotFoundError:
                self.send_json(404, {"error": "该运行还没有可导出的产物。"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="run-{run_id}.zip"')
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        match = re.fullmatch(
            r"/api/runs/([a-f0-9]{12})(?:/((?:experiment|search|source)-[a-f0-9]{8}\.json|report\.md))?",
            path,
        )
        if match:
            run_id, filename = match.groups()
            if filename:
                file = ROOT / "runs" / run_id / filename
                if file.is_file():
                    kind = "application/json" if file.suffix == ".json" else "text/plain"
                    self.send_data(200, file.read_bytes(), kind)
                    return
            else:
                with state_lock:
                    run = runs.get(run_id)
                    data = {**run, "events": list(run["events"])} if run else load_run(
                        ROOT / "runs" / run_id, include_detail=True,
                    )
                if data:
                    self.send_json(200, data)
                    return
        self.send_json(404, {"error": "找不到该资源。"})

    def do_POST(self):
        if self.path != "/api/runs":
            self.send_json(404, {"error": "找不到该接口。"})
            return
        if not self.is_local_request():
            self.send_json(403, {"error": "请从本地工作台启动实验。"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= 16_384:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            question = payload["question"].strip()
            budget = payload["max_experiments"]
            cloud_budget = payload.get("cloud_budget", 15)
            if not 0 < len(question) <= 2000 or type(budget) is not int or not 1 <= budget <= 3:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            self.send_json(400, {"error": "请输入 1–2000 字的研究问题，实验预算为 1–3 次。"})
            return
        if type(cloud_budget) is not int or not 1 <= cloud_budget <= 20:
            self.send_json(400, {"error": "云端调用上限为 1–20 次。"})
            return
        task = payload.get("task")
        if "task" not in payload:
            terms = r"不平衡|分类|类别加权|少数类|逻辑回归|\b(?:classification|class weights?|class_weight|minority class|logistic regression)\b"
            task = "classification" if re.search(terms, question, re.IGNORECASE) else DEFAULT_TASK
        if not isinstance(task, str) or task not in ("prefix_cache", "classification"):
            self.send_json(400, {"error": "请选择有效的研究任务。"})
            return
        with state_lock:
            if any(run["status"] == "running" for run in runs.values()):
                run_id = None
            else:
                run_id = uuid4().hex[:12]
                run = {
                    "status": "running", "events": [], "question": question,
                    "task": task, "created_at": timestamp(),
                }
                save_run(ROOT / "runs" / run_id, run)
                runs[run_id] = run
        if run_id is None:
            self.send_json(HTTPStatus.CONFLICT, {"error": "已有一项研究在运行。"})
            return
        Thread(target=execute, args=(run_id, question, budget, task, cloud_budget)).start()
        self.send_json(HTTPStatus.ACCEPTED, {"id": run_id})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--desktop", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.desktop and os.getpgrp() != os.getpid():
        os.setpgrp()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        if args.desktop:
            print(server.server_port, flush=True)
        else:
            print(f"Research Agent · http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
