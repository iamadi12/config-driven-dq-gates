# Config-Driven Data Quality Gates

A small Python framework that **blocks bad data before it reaches a curated table**.
Rules live in YAML, every rule is `critical` (blocks the write) or `warning` (reported only),
and the upsert into the target happens **all-or-nothing**, only when every critical check passes.

This is the same pattern used in production lakehouse pipelines (quality gates before a Delta `MERGE`),
shown here with pandas so it runs anywhere in seconds.

```
 incoming batch ──► run checks (checks.yaml) ──► gate open?  ──yes──► upsert into target
                                                     │
                                                     └──no───► target unchanged + failure report
```

## Features
- **Declarative rules** – `not_null`, `unique` (composite keys), `in_range`, `accepted_values`, `min_row_count`
- **Severity levels** – critical checks close the gate; warnings are logged but don't block
- **Atomic upsert** – merge on business keys; a failed gate leaves the target untouched
- **Reconciliation** – key-level comparison between two layers (e.g. raw vs curated) that flags
  `missing_in_target`, `extra_in_target` and `value_mismatch`
- **CI** – pytest suite runs on every push via GitHub Actions

## Quick start
```bash
pip install -r requirements.txt
python dq_gates.py      # demo: one clean batch is merged, one bad batch is blocked
pytest -q               # 7 tests
```

Sample output:
```
--- bad batch ---
CHECK                       SEVERITY  STATUS  FAILED ROWS
hcp_id_not_null             critical  FAIL    1
trx_non_negative            critical  FAIL    1
specialty_known             warning   FAIL    1

Gate: CLOSED - write blocked
```

## Adding a rule
```yaml
- name: trx_non_negative
  check: in_range
  column: trx
  min: 0
  severity: critical
```
New check types are one function added to the `CHECKS` registry in `dq_gates.py`.

## Ideas for extension
- Swap pandas for PySpark and the upsert for `DeltaTable.merge`
- Write check results to an audit table for trend monitoring
- Add freshness and distribution-drift checks

*Data in this repo is synthetic.*
