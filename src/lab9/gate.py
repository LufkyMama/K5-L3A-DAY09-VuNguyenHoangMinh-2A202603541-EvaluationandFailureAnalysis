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

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


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
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    man, base_man = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Metric values must be finite numbers (NaN compares False with every threshold).
    for k, v in (pr.get("metrics") or {}).items():
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            problems.append(f"metric {k} is {v!r}, not a number")
        elif not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf)")

    # 2. Row coverage: exactly items x seeds rows, no duplicate (item, seed), same set as baseline.
    seeds = list(man.get("seeds") or [])
    want_rows = int(man.get("items") or 0) * len(seeds)
    if len(rows) != want_rows:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(seeds)} seeds = {want_rows}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    counts: dict = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    dup = sorted((k for k, c in counts.items() if c > 1), key=str)
    if dup:
        problems.append(f"{len(dup)} duplicated (item, seed) row(s), e.g. {dup[:3]}")
    pr_keys, base_keys = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pr_keys != base_keys:
        problems.append(f"(item, seed) set differs from baseline: {len(base_keys - pr_keys)} missing, "
                        f"{len(pr_keys - base_keys)} extra")
    bad_seed = {r.get("seed") for r in rows} - set(seeds)
    if bad_seed:
        problems.append(f"rows use seeds {sorted(bad_seed, key=str)} not in the manifest")
    if sorted(seeds, key=str) != sorted(base_man.get("seeds") or [], key=str):
        problems.append(f"manifest seeds {seeds} differ from baseline {base_man.get('seeds')}")
    if man.get("items") != base_man.get("items"):
        problems.append(f"manifest items {man.get('items')} differ from baseline {base_man.get('items')}")

    # 3. Graders must have run on every row: no evaluator failures, no None / missing value.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for mid in graded:
        missing = sum(1 for r in rows if r.get(mid) is None)
        if missing:
            problems.append(f"{missing} row(s) have no value for graded metric {mid}")

    # 4. Reported metrics must be what the rows say (a hand-edited summary is not a measurement).
    problems += _metrics_match_rows(pr, spec, graded)

    # 5. Slice tags per item must equal the baseline's.
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    relabeled = sorted({r.get("item_id") for r in rows if r.get("item_id") in base_tags
                        and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]}, key=str)
    if relabeled:
        problems.append(f"slice tags differ from baseline for {relabeled[:5]}")

    # 6. Ratchet: on the same eval set a spec may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _metrics_match_rows(pr: dict, spec: dict, graded: list[str]) -> list[str]:
    from lab9.eval import aggregate

    rows = pr.get("rows") or []
    ids = [m for m in graded if rows and all(m in r for r in rows)]
    if not rows or not ids:
        return []
    has_cost = all("cost" in r for r in rows)
    try:
        want = aggregate([{**r, "cost": r.get("cost", 0.0)} for r in rows], ids, k_values=spec.get("pass_k", []))
    except Exception as exc:                       # malformed rows: refuse rather than guess
        return [f"cannot recompute metrics from rows: {exc!r}"]
    out = []
    for k, got in (pr.get("metrics") or {}).items():
        if k not in want or (k == "cost_per_success" and not has_cost):
            continue
        w = want[k]
        if not isinstance(got, (int, float)) or isinstance(got, bool):
            if got is not None or w is not None:
                if got is not None:
                    continue                       # already reported as "not a number"
                out.append(f"metric {k}={got!r} but rows give {w!r}")
            continue
        if w is None or (math.isfinite(got) and abs(float(got) - float(w)) > 1e-3):
            out.append(f"metric {k}={got!r} but rows give {w!r}")
    return out


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    if "max" in base_th and ("max" not in th or th["max"] > base_th["max"]):
        out.append(f"max {base_th['max']} -> {th.get('max')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"min {base_th['min']} -> {th.get('min')}")
    if "max_increase" in base_th and ("max_increase" not in th or th["max_increase"] > base_th["max_increase"]):
        out.append(f"max_increase {base_th['max_increase']} -> {th.get('max_increase')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        out.append(f"ratchet: eval_set_version {base_spec.get('eval_set_version')!r} -> "
                   f"{spec.get('eval_set_version')!r} on an unchanged eval set")
    cur = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = cur.get(bm["id"])
        if m is None:
            out.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {bm['id']} no longer blocking")
        out += [f"ratchet: metric {bm['id']} {x}" for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    cur_s = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        key = (bs.get("name"), bs.get("metric"))
        s = cur_s.get(key)
        if s is None:
            out.append(f"ratchet: slice {key[0]}/{key[1]} removed")
            continue
        if bs.get("blocking") and not s.get("blocking"):
            out.append(f"ratchet: slice {key[0]}/{key[1]} no longer blocking")
        out += [f"ratchet: slice {key[0]}/{key[1]} {x}" for x in _looser(s, bs)]
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        out.append(f"ratchet: seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bb, b = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if (b.get("confidence", 0.95) < bb.get("confidence", 0.95)
            or b.get("n_resamples", 1000) < bb.get("n_resamples", 1000)):
        out.append(f"ratchet: bootstrap {bb} -> {b}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, mid = sl["name"], sl["metric"]
        sid = f"slice:{name}/{mid}"
        a = per_item(pr, mid, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                    # a slice with no items cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                b = per_item(base, mid, slice_name=name)
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label} (n_items={len(a)})")
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
