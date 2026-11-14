import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit
from uuid import uuid4

from research_agent import ROOT, run_research
from archive import build_archive

ASSETS = {
    "/": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
runs = {}
state_lock = Lock()


def execute(run_id, question, budget, cloud_budget=8):
    def on_event(event):
        with state_lock:
            runs[run_id]["events"].append(event)

    try:
        result = run_research(
            question, ROOT / "runs" / run_id, budget, on_event, cloud_budget=cloud_budget
        )
    except Exception as error:
        # Provider errors can contain request metadata. Expose only the status or class.
        status = getattr(error, "status_code", None)
        detail = f"HTTP {status}" if isinstance(status, int) else type(error).__name__
        update = {"status": "failed", "error": f"研究运行失败（{detail}）。请检查模型配置或本地测速环境。"}
    else:
        update = {"status": "complete", "result": result}
    with state_lock:
        runs[run_id].update(update)


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

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_data(200, (ROOT / "web" / filename).read_bytes(), content_type)
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
                    data = {**run, "events": list(run["events"])} if run else None
                if data:
                    self.send_json(200, data)
                    return
        self.send_json(404, {"error": "找不到该资源。"})

    def do_POST(self):
        if self.path != "/api/runs":
            self.send_json(404, {"error": "找不到该接口。"})
            return
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        if host not in allowed_hosts or self.headers.get("Origin") not in (None, f"http://{host}"):
            self.send_json(403, {"error": "请从本地工作台启动实验。"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= 16_384:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            question = payload["question"].strip()
            budget = payload["max_experiments"]
            cloud_budget = payload.get("cloud_budget", 8)
            if (
                not 0 < len(question) <= 2000
                or type(budget) is not int
                or not 1 <= budget <= 3
                or type(cloud_budget) is not int
                or not 1 <= cloud_budget <= 20
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            self.send_json(400, {"error": "请输入 1–2000 字的研究问题，实验预算 1–3 次，云端调用上限 1–20 次。"})
            return
        with state_lock:
            if any(run["status"] == "running" for run in runs.values()):
                run_id = None
            else:
                run_id = uuid4().hex[:12]
                runs[run_id] = {"status": "running", "events": []}
        if run_id is None:
            self.send_json(HTTPStatus.CONFLICT, {"error": "已有一项研究在运行。"})
            return
        Thread(target=execute, args=(run_id, question, budget, cloud_budget)).start()
        self.send_json(HTTPStatus.ACCEPTED, {"id": run_id})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Research Agent · http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
