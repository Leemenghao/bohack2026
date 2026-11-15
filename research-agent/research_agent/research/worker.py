"""Run one benchmark in an isolated process and capture its resource usage."""

import argparse
import json
import resource
import sys
import contextlib
import io
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=("classification", "prefix_cache", "kernel", "python"))
    parser.add_argument("output", type=Path)
    parser.add_argument("configuration")
    args = parser.parse_args()
    configuration = json.loads(args.configuration)
    result = {}
    try:
        if args.task in ("kernel", "python"):
            resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
            resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        if args.task == "kernel":
            from research_agent.benchmark.row_normalization import run_benchmark
            result = run_benchmark(**configuration)
        elif args.task == "python":
            class Output(io.TextIOBase):
                def __init__(self): self.text = ""
                def write(self, value):
                    self.text += str(value)[:max(0, 12000 - len(self.text))]
                    return len(value)
                def flush(self): pass
            capture = Output()
            try:
                with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
                    runpy.run_path(configuration["source"], run_name="__main__")
            finally:
                result = {"summary": {"output": capture.text, "output_limit": 12000}}
        elif args.task == "classification":
            from research_agent.benchmark.imbalanced_classification import run_benchmark
            result = run_benchmark(configuration["split_seed"])
        else:
            from research_agent.benchmark.prefix_cache import run_benchmark
            result = run_benchmark(**configuration)
            result = {"summary": result["summary"][configuration["workload"]], "requests": result["runs"]}
    except Exception as error:
        result["error"] = type(error).__name__
    finally:
        own = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["resources"] = {
            "cpu_seconds": round(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime, 4),
            "peak_process_rss_bytes": int(max(own.ru_maxrss, children.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)),
            "measurement_scope": "CPU includes worker and reaped children; RSS is largest process high-water mark, not simultaneous process-tree memory.",
        }
        args.output.write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
