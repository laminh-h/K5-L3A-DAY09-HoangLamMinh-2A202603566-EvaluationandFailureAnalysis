"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Beyond the list: duplicated (item, seed) rows even when the count still matches, rows whose
    seed the manifest does not list, non-boolean row values, and metrics that the report's own rows
    do not reproduce (a hand-edited metric block)."""
    problems: list[str] = []
    problems += _report_problems(pr, spec, "")
    problems += _report_problems(base, spec, "baseline: ", recompute=False)
    problems += _coverage_problems(pr, base)
    problems += _slice_tag_problems(pr, base)
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _is_bad_number(v: Any) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _graded_ids(spec: dict) -> list[str]:
    """Spec metrics scored per row by a registered grader (the others are aggregates)."""
    from lab9.graders import GRADERS
    return [m["id"] for m in spec.get("metrics") or [] if m.get("id") in GRADERS]


def _report_problems(rep: dict, spec: dict, who: str, recompute: bool = True) -> list[str]:
    """Problems visible inside one report: non-finite metrics, a row count that does not match the
    manifest, duplicated (item, seed) rows, crashed graders, and metrics its own rows do not reproduce."""
    out: list[str] = []
    metrics, rows, man = rep.get("metrics"), rep.get("rows"), rep.get("manifest") or {}
    if not isinstance(metrics, dict) or not isinstance(rows, list) or not rows:
        return [f"{who}report has no metrics or no rows"]
    out += [f"{who}metric {k} is {v} (NaN/inf never compares as a failure)"
            for k, v in metrics.items() if _is_bad_number(v)]
    try:
        want = int(man["items"]) * len(man["seeds"])
    except (KeyError, TypeError, ValueError):
        want = None
        out.append(f"{who}manifest lacks items/seeds: cannot check the row count")
    if want is not None and len(rows) != want:
        out.append(f"{who}{len(rows)} rows, manifest says {man.get('items')} items x "
                   f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seen: set = set()
    dup = sorted({k for k in keys if k in seen or seen.add(k)}, key=str)
    if dup:
        out.append(f"{who}duplicated (item, seed) rows: {dup[:5]}")
    if want is not None:
        stray = sorted({r.get("seed") for r in rows} - set(man["seeds"]), key=str)
        if stray:
            out.append(f"{who}rows carry seeds {stray} that the manifest does not list")
    failures = rep.get("evaluator_failures", [])
    if not isinstance(failures, list):
        out.append(f"{who}evaluator_failures is not a list")
    elif failures:
        out.append(f"{who}{len(failures)} evaluator failure(s), first: {str(failures[0])[:80]}")
    for m in _graded_ids(spec):
        if not any(m in r for r in rows) and m not in metrics:
            continue                                   # metric not part of this run at all
        none = sum(1 for r in rows if r.get(m) is None)
        if none:
            out.append(f"{who}{none} row(s) with no value for graded metric {m} "
                       f"(a crashed grader drops out of the mean)")
        odd = sum(1 for r in rows if r.get(m) is not None and not isinstance(r.get(m), bool))
        if odd:
            out.append(f"{who}{odd} row(s) with a non-boolean value for {m}")
    if recompute and not out:
        out += [f"{who}{p}" for p in _recompute_problems(rep, spec)]
    return out


def _recompute_problems(rep: dict, spec: dict) -> list[str]:
    """Re-aggregate the rows with the harness's own function; every reported metric must match."""
    from lab9.eval import aggregate
    rows, metrics = rep["rows"], rep["metrics"]
    ids = [m for m in metrics if all(isinstance(r.get(m), bool) for r in rows)]
    try:
        again = aggregate(rows, ids, k_values=spec.get("pass_k", []))
    except (KeyError, TypeError, ValueError):          # hand-built rows without a cost column
        again = {m: (sum(r[m] for r in rows) if m in ("secret_leak", "approval_bypass")
                     else round(sum(r[m] for r in rows) / len(rows), 4)) for m in ids}
    out = []
    for k, v in metrics.items():
        if k not in again or isinstance(v, bool):
            continue
        w = again[k]
        if isinstance(v, (int, float)) and isinstance(w, (int, float)):
            if abs(float(v) - float(w)) > 1e-3:
                out.append(f"metric {k}={v} but its own rows give {w}")
        elif (v is None) != (w is None):
            out.append(f"metric {k}={v} but its own rows give {w}")
    return out


def _coverage_problems(pr: dict, base: dict) -> list[str]:
    """PR and baseline must grade the same (item, seed) pairs: no cherry-picked seeds or items."""
    out = []
    pk = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    bk = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pk != bk:
        miss, extra = sorted(bk - pk, key=str), sorted(pk - bk, key=str)
        out.append(f"(item, seed) set differs from the baseline: {len(miss)} missing {miss[:4]}, "
                   f"{len(extra)} extra {extra[:4]}")
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        out.append(f"seeds {pm.get('seeds')} differ from the baseline's {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        out.append(f"manifest items {pm.get('items')} differ from the baseline's {bm.get('items')}")
    return out


def _slices_by_item(rep: dict) -> dict[Any, set[tuple[str, ...]]]:
    acc: dict[Any, set[tuple[str, ...]]] = {}
    for r in rep.get("rows") or []:
        acc.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    return acc


def _slice_tag_problems(pr: dict, base: dict) -> list[str]:
    """An item's slice tags come from its label; moving an item out of a slice hides its regression."""
    out = []
    ps, bs = _slices_by_item(pr), _slices_by_item(base)
    for item in sorted(ps, key=str):
        if len(ps[item]) > 1:
            out.append(f"{item}: rows disagree on slice tags {sorted(ps[item])}")
        elif item in bs and ps[item] != bs[item]:
            out.append(f"{item}: slice tags {sorted(ps[item])} differ from the baseline's {sorted(bs[item])}")
    return out


def _looser(th: dict, base_th: dict, where: str) -> list[str]:
    out = []
    if "max" in base_th and not ("max" in th and th["max"] <= base_th["max"]):
        out.append(f"{where}: max {th.get('max')} is looser than {base_th['max']}")
    if "min" in base_th and not ("min" in th and th["min"] >= base_th["min"]):
        out.append(f"{where}: min {th.get('min')} is looser than {base_th['min']}")
    if "max_increase" in base_th and not ("max_increase" in th and th["max_increase"] <= base_th["max_increase"]):
        out.append(f"{where}: max_increase {th.get('max_increase')} is looser than {base_th['max_increase']}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop removed")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold may only get stricter (a new version starts over)."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out = []
    mine = {m.get("id"): m for m in spec.get("metrics") or []}
    for bm in base_spec.get("metrics") or []:
        mid, m = bm.get("id"), mine.get(bm.get("id"))
        if m is None:
            out.append(f"ratchet: metric {mid} removed from the spec")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {mid} is no longer blocking")
        out += [f"ratchet: {p}" for p in _looser(m.get("threshold") or {}, bm.get("threshold") or {}, mid)]
    mine_sl = {(x.get("name"), x.get("metric")): x for x in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        key = (bsl.get("name"), bsl.get("metric"))
        where, x = f"slice:{key[0]}/{key[1]}", mine_sl.get(key)
        if x is None:
            out.append(f"ratchet: {where} removed from the spec")
            continue
        if bsl.get("blocking") and not x.get("blocking"):
            out.append(f"ratchet: {where} is no longer blocking")
        out += [f"ratchet: {p}" for p in _looser(x, bsl, where)]
    for key in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"ratchet: {key} changed from {base_spec.get(key)!r} to {spec.get(key)!r} "
                       f"on the same eval-set version")
    if sorted(base_spec.get("seeds") or []) != sorted(spec.get("seeds") or []):
        out.append(f"ratchet: seeds changed from {base_spec.get('seeds')} to {spec.get('seeds')}")
    gone_k = sorted(set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []))
    if gone_k:
        out.append(f"ratchet: pass_k {gone_k} removed")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if sb.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append(f"ratchet: bootstrap confidence raised to {sb.get('confidence')} (a wider CI hides drops)")
    if sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        out.append(f"ratchet: bootstrap n_resamples lowered to {sb.get('n_resamples')}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl.get("metric", "pass_rate")
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                        # an empty slice cannot vouch for anything
        else:
            if "max" in sl:                            # safety slice: count of flagged rows
                val = sum(1 for r in pr["rows"] if name in (r.get("slices") or []) and r.get(metric) is True)
                if val > sl["max"]:
                    verdict = "fail"
            else:
                val = round(sum(a.values()) / len(a), 4)
                if "min" in sl and val < sl["min"]:
                    verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<7} n={len(a):<3} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
