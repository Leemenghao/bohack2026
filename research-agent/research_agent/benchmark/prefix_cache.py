import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def measure(port, prompt):
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first_token = None
    parts = []
    usage = {}
    with urlopen(request, timeout=30) as response:
        for line in response:
            if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                continue
            event = json.loads(line[6:])
            usage = event.get("usage") or usage
            for choice in event["choices"]:
                content = choice["delta"].get("content")
                if content:
                    if first_token is None:
                        first_token = time.perf_counter()
                    parts.append(content)
    if first_token is None or not usage.get("completion_tokens"):
        raise RuntimeError("The server returned no measurable completion")
    return {
        "ttft_ms": round((first_token - started) * 1000, 2),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "prompt_tokens": usage["prompt_tokens"],
        "cached_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
        "output_tokens": usage["completion_tokens"],
        "text": "".join(parts),
    }


def run_server(model, port, cache_size, workloads):
    with tempfile.TemporaryFile(mode="w+t") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "mlx_lm.server", "--model", model,
             "--host", "127.0.0.1", "--port", str(port),
             "--prompt-cache-size", str(cache_size),
             "--chat-template-args", '{"enable_thinking":false}'],
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and server.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1):
                        break
                except URLError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("MLX server did not become ready")
            measure(port, "Warmup. Write a short greeting.")
            measure(port, "Warmup. Name a city.")
            return {
                name: [measure(port, prompt) for prompt in prompts]
                for name, prompts in workloads.items()
            }
        except Exception:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def run_benchmark(model, port=18937, cache_first=False, workload=None):
    terms = ["forest", "ocean", "valley", "island", "desert", "garden", "river", "mountain"]
    workloads = {
        "shared": [f"{'astronomy ' * 1500}\nWrite one sentence about {term}." for term in terms],
        "different": [f"{(term + ' ') * 1500}\nWrite one sentence about local inference." for term in terms],
    }
    if workload is not None:
        workloads = {workload: workloads[workload]}
    cache_sizes = (8, 0) if cache_first else (0, 8)
    runs = {size: run_server(model, port, size, workloads) for size in cache_sizes}
    summary = {}
    for name in workloads:
        start = 1 if name == "shared" else 0
        off = runs[0][name][start:]
        on = runs[8][name][start:]
        summary[name] = {
            "requests_per_arm": len(off),
            "median_ttft_ms_off": statistics.median(row["ttft_ms"] for row in off),
            "median_ttft_ms_on": statistics.median(row["ttft_ms"] for row in on),
            "median_cached_tokens_on": statistics.median(row["cached_tokens"] for row in on),
            "matching_texts": sum(a["text"] == b["text"] for a, b in zip(off, on)),
        }
    return {"summary": summary, "runs": runs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--port", type=int, default=18937)
    parser.add_argument("--cache-first", action="store_true")
    parser.add_argument("--workload", choices=("shared", "different"))
    args = parser.parse_args()
    result = run_benchmark(args.model, args.port, args.cache_first, args.workload)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
