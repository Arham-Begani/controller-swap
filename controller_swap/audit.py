"""Finite-sample collision audit. This is not an empirical attribution experiment."""
from collections import Counter, defaultdict

from .core import MODES, VIEWS, canonical, digest, evidence_view, verify_chain


def collision_audit(runs, split="evaluation"):
    """Group by the entire canonical evaluator input, never by hidden labels.

    For a deterministic function of this input alone, at most the largest label
    count in each equivalence class can be correct. Summing gives an exact ceiling
    on this fixed multiset. It is not a held-out estimate or population bound.
    """
    selected = [r for r in runs if r.get("status") == "complete"
                and (split == "all" or r["split"] == split) and verify_chain(r)]
    strata = defaultdict(list)
    for run in selected:
        strata[(run["scope"], run["protocol_hash"], run["backend"])].append(run)
    summaries = []
    for (scope, protocol, backend), group in sorted(strata.items()):
        for view in VIEWS:
            classes = defaultdict(list)
            for run in group:
                # Canonical text itself is the key, so a hash collision cannot merge inputs.
                classes[canonical(evidence_view(run, view))].append(run)
            majority_correct, ambiguous_runs, conflicts = 0, 0, []
            for serialized, members in sorted(classes.items()):
                counts = Counter(r["mode"] for r in members)
                majority_correct += max(counts.values())
                if len(counts) > 1:
                    ambiguous_runs += len(members)
                    conflicts.append({"evidence_sha256": digest(evidence_view(members[0], view)),
                                      "label_counts": {m: counts[m] for m in MODES},
                                      "run_ids": sorted(r["id"] for r in members)})
            summaries.append({"scope": scope, "protocol_hash": protocol, "backend": backend,
                              "view": view, "n": len(group), "distinct_inputs": len(classes),
                              "conflicting_inputs": len(conflicts), "ambiguous_runs": ambiguous_runs,
                              "max_correct_from_input_alone": majority_correct,
                              "empirical_accuracy_ceiling": majority_correct / len(group),
                              "minimum_empirical_errors": len(group) - majority_correct,
                              "conflicts": conflicts})
    return {"schema": "controller-swap-collision-audit/v1", "split": split,
            "summaries": summaries,
            "interpretation": "Exact finite-multiset ceiling for a deterministic predictor of the supplied evidence alone. Repetitions are not independent. No generalization, model performance, causal influence or universal impossibility claim follows. Complete-view fixture labels are explicit; collisions in synthetic views are constructed diagnostics, not discoveries about real agents."}
