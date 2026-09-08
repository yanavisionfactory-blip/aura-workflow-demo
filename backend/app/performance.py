"""Observed latency baselines, with explicit sample-size and workload boundaries."""
import math


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def evaluate_performance(samples, targets=None, minimum_samples=30):
    fields = ("planning_time_ms", "time_to_first_useful_result_ms", "execution_delivery_time_ms", "total_completion_time_ms", "agent_call_count", "failed_provider_attempts")
    metrics = {}
    for field in fields:
        values = [row[field] for row in samples if isinstance(row.get(field), (int, float)) and row[field] >= 0]
        metrics[field] = {"samples": len(values), "p50": percentile(values, .5), "p95": percentile(values, .95)}
    regressions = []
    for field, ceiling in (targets or {}).items():
        metric = metrics.get(field)
        if metric and metric["samples"] >= minimum_samples and metric["p95"] > ceiling:
            regressions.append(field)
    enough = bool(targets) and all(metrics.get(field, {}).get("samples", 0) >= minimum_samples for field in targets)
    return {"status": "failed" if regressions else "passed" if enough else "insufficient_data" if targets else "baseline_only",
        "metrics": metrics, "regressions": regressions, "minimum_samples": minimum_samples,
        "targets": targets or {}, "note": "Completion wall time includes approval waits; active execution time does not."}
