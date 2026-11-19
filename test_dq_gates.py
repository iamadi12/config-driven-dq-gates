import pandas as pd

from dq_gates import gate_passed, load_config, merge_if_passed, reconcile, run_checks

CFG = load_config("checks.yaml")


def frame(rows):
    return pd.DataFrame(rows, columns=["hcp_id", "month", "trx", "specialty"])


def test_clean_batch_passes():
    df = frame([["H1", "2026-01", 10, "ONC"], ["H2", "2026-01", 5, "PCP"]])
    assert gate_passed(run_checks(df, CFG))


def test_null_key_blocks_gate():
    df = frame([[None, "2026-01", 10, "ONC"]])
    results = run_checks(df, CFG)
    assert not gate_passed(results)
    assert next(r for r in results if r.name == "hcp_id_not_null").failed_rows == 1


def test_duplicate_key_blocks_gate():
    df = frame([["H1", "2026-01", 10, "ONC"], ["H1", "2026-01", 3, "ONC"]])
    assert not gate_passed(run_checks(df, CFG))


def test_warning_does_not_block():
    df = frame([["H1", "2026-01", 10, "UNKNOWN"]])
    results = run_checks(df, CFG)
    assert gate_passed(results)
    assert not next(r for r in results if r.name == "specialty_known").passed


def test_merge_is_all_or_nothing():
    target = frame([["H1", "2026-01", 10, "ONC"]])
    bad = frame([["H1", "2026-01", -1, "ONC"]])
    merged, _ = merge_if_passed(target, bad, ["hcp_id", "month"], CFG)
    assert merged.equals(target)


def test_merge_upserts_on_success():
    target = frame([["H1", "2026-01", 10, "ONC"]])
    updates = frame([["H1", "2026-01", 12, "ONC"], ["H2", "2026-01", 4, "PCP"]])
    merged, _ = merge_if_passed(target, updates, ["hcp_id", "month"], CFG)
    assert len(merged) == 2
    assert merged.loc[merged.hcp_id == "H1", "trx"].item() == 12


def test_reconcile_flags_differences():
    src = frame([["H1", "2026-01", 10, "ONC"], ["H2", "2026-01", 5, "PCP"]])
    tgt = frame([["H1", "2026-01", 9, "ONC"], ["H3", "2026-01", 1, "PCP"]])
    status = dict(zip(reconcile(src, tgt, ["hcp_id"], "trx")["hcp_id"],
                      reconcile(src, tgt, ["hcp_id"], "trx")["status"]))
    assert status == {"H1": "value_mismatch", "H2": "missing_in_target", "H3": "extra_in_target"}
