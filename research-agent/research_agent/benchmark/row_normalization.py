"""Fixed evaluator for model-written row-L2-normalization candidates.

Candidate code is a restricted numeric function, not general Python execution.
The reference, inputs and measurement code are never supplied by the model.
"""
import argparse
import ast
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

import numpy as np

BASELINE = """def normalize(x):
    out = np.zeros_like(x)
    for i in range(len(x)):
        denom = np.sqrt(np.sum(x[i] * x[i]))
        out[i] = x[i] / np.maximum(denom, 1e-12)
    return out
"""
FUNCTIONS = {"sum", "sqrt", "maximum", "where", "einsum", "square", "multiply", "divide", "zeros_like", "abs"}
ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Return,
           ast.For, ast.If, ast.Expr, ast.Name, ast.Load, ast.Store, ast.Constant,
           ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice, ast.Tuple,
           ast.BinOp, ast.UnaryOp, ast.Compare, ast.Add, ast.Sub, ast.Mult, ast.Div,
           ast.Pow, ast.USub, ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def validate_code(code):
    if not isinstance(code, str) or len(code) > 6000:
        raise ValueError("Provide at most 6000 characters.")
    tree = ast.parse(code)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Define only normalize(x), without imports.")
    fn = tree.body[0]
    if (fn.name != "normalize" or fn.decorator_list or fn.returns or fn.args.defaults
            or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.posonlyargs
            or len(fn.args.args) != 1 or fn.args.args[0].arg != "x" or fn.args.args[0].annotation):
        raise ValueError("Expected def normalize(x).")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("Nested functions are not supported.")
        if not isinstance(node, ALLOWED):
            raise ValueError(f"Unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or
                isinstance(node.ctx, ast.Store) and node.id in {"np", "range", "len", "normalize"}):
            raise ValueError("Reserved name.")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.ctx, ast.Load):
                raise ValueError("Attributes are read-only.")
            if not (isinstance(node.value, ast.Name) and node.value.id == "np" and node.attr in FUNCTIONS
                    or isinstance(node.value, ast.Name) and node.value.id == "x" and node.attr in {"shape", "dtype"}):
                raise ValueError("Only approved np functions and x.shape/x.dtype are available.")
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "np" and node.func.attr in FUNCTIONS
                    or isinstance(node.func, ast.Name) and node.func.id in {"range", "len"}):
                raise ValueError("Unsupported call.")
    return tree


def load_candidate(code):
    tree = validate_code(code)
    namespace = {"np": np, "range": range, "len": len, "__builtins__": {}}
    exec(compile(tree, "<numeric-candidate>", "exec"), namespace)
    return namespace["normalize"]


def run_benchmark(code, suite="development"):
    if suite not in {"development", "validation"}:
        raise ValueError("Unknown suite")
    candidate = load_candidate(code)
    baseline = load_candidate(BASELINE)
    rng = np.random.default_rng(42 if suite == "development" else 731)
    shapes = [(32, 64), (256, 256), (1024, 512)] if suite == "development" else [(17, 33), (257, 129), (2048, 256)]
    cases = []
    for shape in shapes:
        x = rng.normal(size=shape).astype(np.float32)
        x[0] = 0
        x[1] *= 1e-14
        x.setflags(write=False)
        reference = x / np.maximum(np.sqrt(np.sum(x.astype(np.float64) ** 2, axis=1, keepdims=True)), 1e-12)
        try:
            result = candidate(x)
            valid = (isinstance(result, np.ndarray) and result.shape == x.shape
                     and result.dtype == x.dtype and np.isfinite(result).all()
                     and np.allclose(result, reference, rtol=2e-5, atol=2e-6))
            error = float(np.max(np.abs(result - reference))) if valid else None
        except Exception as exc:
            return {"summary": {"correct": False, "suite": suite, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                                "cases": cases, "code_sha256": hashlib.sha256(code.encode()).hexdigest()}}
        case = {"shape": list(shape), "correct": bool(valid), "max_abs_error": error}
        cases.append(case)
        if not valid:
            continue
        samples = {"baseline": [], "candidate": []}
        for _ in range(3):
            baseline(x)
            candidate(x)
        for repeat in range(9):
            order = [("baseline", baseline), ("candidate", candidate)]
            if repeat % 2:
                order.reverse()
            for label, function in order:
                start = time.perf_counter_ns()
                for _ in range(3):
                    function(x)
                samples[label].append((time.perf_counter_ns() - start) / 3e6)
        case.update(baseline_ms=statistics.median(samples["baseline"]),
                    candidate_ms=statistics.median(samples["candidate"]), samples_ms=samples)
        case["speedup"] = case["baseline_ms"] / max(case["candidate_ms"], 1e-9)
    return {"summary": {"correct": all(case["correct"] for case in cases), "suite": suite, "cases": cases,
                        "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                        "measurement": {"dtype": "float32", "warmups": 3, "repeats": 9, "calls_per_sample": 3,
                                        "statistic": "median", "rtol": 2e-5, "atol": 2e-6},
                        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                                        "machine": platform.machine(), "platform": platform.platform()},
                        "method": "float32; 3 warmups; 9 alternating paired repeats, 3 calls/sample; median; tolerance rtol=2e-5, atol=2e-6"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--suite", choices=("development", "validation"), default="validation")
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.candidate.read_text(), args.suite), ensure_ascii=False, indent=2))
