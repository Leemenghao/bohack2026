"""Compact model context while preserving the complete measurement on disk."""
import copy
import statistics


def compact_evidence(record):
    result = copy.deepcopy(record)
    for case in result.get("summary", {}).get("cases", []):
        samples = case.pop("samples_ms", {})
        for label, values in samples.items():
            if values:
                median = statistics.median(values)
                case[f"{label}_mad_ms"] = statistics.median(abs(v - median) for v in values)
    return result
