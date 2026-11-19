"""Config-driven data quality gates.

Checks are declared in YAML. Each check is either `critical` (blocks the
write) or `warning` (reported only). Data is merged into the target only
when every critical check passes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd
import yaml


@dataclass
class CheckResult:
    name: str
    check: str
    severity: str
    passed: bool
    failed_rows: int
    detail: str = ""


# ---------- check implementations: each returns a boolean mask of BAD rows ----------

def _not_null(df: pd.DataFrame, column: str, **_) -> pd.Series:
    return df[column].isna()


def _unique(df: pd.DataFrame, columns: list[str], **_) -> pd.Series:
    return df.duplicated(subset=columns, keep=False)


def _in_range(df: pd.DataFrame, column: str, min=None, max=None, **_) -> pd.Series:
    bad = pd.Series(False, index=df.index)
    if min is not None:
        bad |= df[column] < min
    if max is not None:
        bad |= df[column] > max
    return bad


def _accepted_values(df: pd.DataFrame, column: str, values: list, **_) -> pd.Series:
    return ~df[column].isin(values)


CHECKS: dict[str, Callable[..., pd.Series]] = {
    "not_null": _not_null,
    "unique": _unique,
    "in_range": _in_range,
    "accepted_values": _accepted_values,
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_checks(df: pd.DataFrame, config: dict) -> list[CheckResult]:
    results: list[CheckResult] = []

    min_rows = config.get("min_row_count")
    if min_rows is not None:
        ok = len(df) >= min_rows
        results.append(CheckResult("min_row_count", "row_count", "critical", ok,
                                   0 if ok else 1, f"{len(df)} rows, expected >= {min_rows}"))

    for spec in config.get("checks", []):
        spec = dict(spec)
        name = spec.pop("name")
        kind = spec.pop("check")
        severity = spec.pop("severity", "critical")
        if kind not in CHECKS:
            raise ValueError(f"Unknown check type: {kind}")
        bad = CHECKS[kind](df, **spec)
        n_bad = int(bad.sum())
        results.append(CheckResult(name, kind, severity, n_bad == 0, n_bad))
    return results


def reconcile(source: pd.DataFrame, target: pd.DataFrame, keys: list[str], measure: str,
              tolerance: float = 0.0) -> pd.DataFrame:
    """Key-level comparison of a measure between two layers (e.g. raw vs curated)."""
    s = source.groupby(keys, as_index=False)[measure].sum()
    t = target.groupby(keys, as_index=False)[measure].sum()
    m = s.merge(t, on=keys, how="outer", suffixes=("_source", "_target"), indicator=True)
    m["diff"] = m[f"{measure}_target"].fillna(0) - m[f"{measure}_source"].fillna(0)
    m["status"] = "match"
    m.loc[m["_merge"] == "left_only", "status"] = "missing_in_target"
    m.loc[m["_merge"] == "right_only", "status"] = "extra_in_target"
    mismatch = (m["_merge"] == "both") & (m["diff"].abs() > tolerance)
    m.loc[mismatch, "status"] = "value_mismatch"
    return m.drop(columns="_merge")


def gate_passed(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results if r.severity == "critical")


def merge_if_passed(target: pd.DataFrame, updates: pd.DataFrame, keys: list[str],
                    config: dict) -> tuple[pd.DataFrame, list[CheckResult]]:
    """Upsert `updates` into `target` on `keys`, but only if all critical checks pass.

    The merge is all-or-nothing: on failure the original target is returned unchanged.
    """
    results = run_checks(updates, config)
    if not gate_passed(results):
        return target, results
    kept = target.merge(updates[keys], on=keys, how="left", indicator=True)
    kept = kept[kept["_merge"] == "left_only"].drop(columns="_merge")
    merged = pd.concat([kept, updates], ignore_index=True)
    return merged, results


def report(results: list[CheckResult]) -> str:
    lines = [f"{'CHECK':<28}{'SEVERITY':<10}{'STATUS':<8}FAILED ROWS"]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"{r.name:<28}{r.severity:<10}{status:<8}{r.failed_rows}")
    lines.append(f"\nGate: {'OPEN - safe to write' if gate_passed(results) else 'CLOSED - write blocked'}")
    return "\n".join(lines)


if __name__ == "__main__":
    cfg = load_config("checks.yaml")
    target = pd.DataFrame({"hcp_id": ["H1", "H2"], "month": ["2026-01", "2026-01"],
                           "trx": [10, 20], "specialty": ["ONC", "CARD"]})
    good = pd.DataFrame({"hcp_id": ["H2", "H3"], "month": ["2026-01", "2026-01"],
                         "trx": [25, 5], "specialty": ["CARD", "ONC"]})
    bad = pd.DataFrame({"hcp_id": ["H4", None], "month": ["2026-01", "2026-01"],
                        "trx": [-3, 7], "specialty": ["XYZ", "ONC"]})

    for label, batch in [("good batch", good), ("bad batch", bad)]:
        target, res = merge_if_passed(target, batch, ["hcp_id", "month"], cfg)
        print(f"--- {label} ---\n{report(res)}\n")
    print("Final target:\n", target)
    print("\nReconciliation (raw vs curated):")
    print(reconcile(good, target, ["hcp_id"], "trx"))
