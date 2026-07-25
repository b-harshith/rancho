import json
import math
import random
from collections import Counter
from pathlib import Path

import h3
import numpy as np


DATA_DIR = Path("DATA")
MASTER_JSON = DATA_DIR / "processed" / "stage2_hex7_affluence_master.json"
OUTPUT_JSON = DATA_DIR / "audits" / "stage2_hex7_affluence_spatial_diagnostics.json"
OUTPUT_MD = DATA_DIR / "audits" / "stage2_hex7_affluence_spatial_diagnostics.md"

PERMUTATIONS = 999
RANDOM_SEED = 42


def load_records():
    with MASTER_JSON.open("r") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f"{MASTER_JSON} must contain a list of records.")
    return records


def pearson(xs, ys):
    clean = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(clean) < 3:
        return None
    a = np.array([x for x, _ in clean], dtype=float)
    b = np.array([y for _, y in clean], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def adjacency(hex_ids):
    cells = set(hex_ids)
    return {
        hex_id: sorted(cell for cell in h3.grid_disk(hex_id, 1) if cell != hex_id and cell in cells)
        for hex_id in hex_ids
    }


def morans_i(values_by_hex, neighbors):
    hex_ids = list(values_by_hex)
    values = np.array([float(values_by_hex[hex_id]) for hex_id in hex_ids], dtype=float)
    mean = float(np.mean(values))
    deviations = {hex_id: float(values_by_hex[hex_id]) - mean for hex_id in hex_ids}
    denominator = sum(value * value for value in deviations.values())
    weight_sum = sum(len(neighbors[hex_id]) for hex_id in hex_ids)
    if denominator == 0 or weight_sum == 0:
        return None
    numerator = 0.0
    for hex_id in hex_ids:
        for neighbor in neighbors[hex_id]:
            numerator += deviations[hex_id] * deviations[neighbor]
    return (len(hex_ids) / weight_sum) * (numerator / denominator)


def permutation_test(values_by_hex, neighbors, observed_i):
    if observed_i is None:
        return {"permutations": 0, "p_value_two_sided": None}
    rng = random.Random(RANDOM_SEED)
    hex_ids = list(values_by_hex)
    values = [float(values_by_hex[hex_id]) for hex_id in hex_ids]
    extreme = 0
    simulated = []
    for _ in range(PERMUTATIONS):
        shuffled = values[:]
        rng.shuffle(shuffled)
        shuffled_values = dict(zip(hex_ids, shuffled))
        score = morans_i(shuffled_values, neighbors)
        simulated.append(score)
        if abs(score) >= abs(observed_i):
            extreme += 1
    return {
        "permutations": PERMUTATIONS,
        "p_value_two_sided": (extreme + 1) / (PERMUTATIONS + 1),
        "simulated_mean": float(np.mean(simulated)),
        "simulated_std": float(np.std(simulated)),
        "simulated_min": float(np.min(simulated)),
        "simulated_max": float(np.max(simulated)),
    }


def quantile(values, q):
    return float(np.percentile([float(v) for v in values], q))


def neighbor_mean(record_by_hex, neighbors, field_getter, hex_id):
    values = [field_getter(record_by_hex[neighbor]) for neighbor in neighbors[hex_id]]
    return sum(values) / len(values) if values else 0.0


def classify_spatial_buckets(records, neighbors):
    record_by_hex = {record["hex_id"]: record for record in records}
    scores = [record["final_affluence_score"] for record in records]
    p25 = quantile(scores, 25)
    p50 = quantile(scores, 50)
    p75 = quantile(scores, 75)
    buckets = Counter()
    examples = {key: [] for key in ["high_high", "high_low", "low_high", "low_low"]}

    for record in records:
        hex_id = record["hex_id"]
        score = record["final_affluence_score"]
        n_mean = neighbor_mean(
            record_by_hex, neighbors, lambda item: item["final_affluence_score"], hex_id
        )
        if score >= p75 and n_mean >= p75:
            key = "high_high"
        elif score >= p75 and n_mean < p50:
            key = "high_low"
        elif score < p50 and n_mean >= p75:
            key = "low_high"
        elif score <= p25 and n_mean <= p25:
            key = "low_low"
        else:
            key = "mixed"
        buckets[key] += 1
        if key in examples and len(examples[key]) < 10:
            examples[key].append(
                {
                    "rank": record["rank"],
                    "hex_id": hex_id,
                    "name": record.get("name"),
                    "final_affluence_score": record["final_affluence_score"],
                    "neighbor_mean_score": round(n_mean, 4),
                    "tier": record["affluence_tier"],
                }
            )
    return {
        "thresholds": {"p25": p25, "p50": p50, "p75": p75},
        "bucket_counts": dict(buckets),
        "examples": examples,
    }


def model_diagnostics(records):
    top25 = records[:25]
    top50 = records[:50]
    top100 = records[:100]
    bottom100 = records[-100:]

    def count_no_direct(items):
        return sum("no_direct_society_tam" in record.get("quality_flags", []) for record in items)

    def evidence_count(items, evidence_group):
        return sum(1 for record in items if record["top_evidence"].get(evidence_group))

    direct_tam = [record["tam"]["direct_family_tam"] for record in records]
    final_scores = [record["final_affluence_score"] for record in records]
    cluster_tam = [record["tam"]["society_cluster_tam_weighted"] for record in records]
    surrounding_cluster_tam = [
        record["tam"]["surrounding_affluent_cluster_tam_weighted"] for record in records
    ]
    society_scores = [record["component_scores"]["society_score"] for record in records]
    school_scores = [record["component_scores"]["school_score"] for record in records]
    market_scores = [record["component_scores"]["market_score"] for record in records]
    sez_scores = [record["component_scores"]["sez_workplace_score"] for record in records]

    high_score_low_residential = [
        {
            "rank": record["rank"],
            "hex_id": record["hex_id"],
            "name": record.get("name"),
            "final_affluence_score": record["final_affluence_score"],
            "society_score": record["component_scores"]["society_score"],
            "society_cluster_score": record["component_scores"]["society_cluster_score"],
            "direct_family_tam": record["tam"]["direct_family_tam"],
            "sez_workplace_score": record["component_scores"]["sez_workplace_score"],
        }
        for record in records
        if record["final_affluence_score"] >= 55
        and record["component_scores"]["society_score"] < 0.30
    ]

    no_direct_cluster_supported = [
        {
            "rank": record["rank"],
            "hex_id": record["hex_id"],
            "name": record.get("name"),
            "final_affluence_score": record["final_affluence_score"],
            "tier": record["affluence_tier"],
            "society_cluster_score": record["component_scores"]["society_cluster_score"],
            "society_cluster_tam_weighted": record["tam"]["society_cluster_tam_weighted"],
            "surrounding_affluent_cluster_tam_weighted": record["tam"][
                "surrounding_affluent_cluster_tam_weighted"
            ],
        }
        for record in records
        if record["tam"]["direct_family_tam"] == 0
        and record["component_scores"]["society_cluster_score"] >= 0.40
    ][:25]

    return {
        "coverage": {
            "top25_no_direct_society_tam": count_no_direct(top25),
            "top50_no_direct_society_tam": count_no_direct(top50),
            "top100_no_direct_society_tam": count_no_direct(top100),
            "bottom100_no_direct_society_tam": count_no_direct(bottom100),
            "top50_with_society_evidence": evidence_count(top50, "societies"),
            "top50_with_school_evidence": evidence_count(top50, "schools"),
            "top50_with_hospital_evidence": evidence_count(top50, "hospitals"),
        },
        "correlations": {
            "final_vs_log1p_direct_family_tam": pearson(
                final_scores, [math.log1p(value) for value in direct_tam]
            ),
            "final_vs_log1p_society_cluster_tam_weighted": pearson(
                final_scores, [math.log1p(value) for value in cluster_tam]
            ),
            "final_vs_log1p_surrounding_affluent_cluster_tam_weighted": pearson(
                final_scores, [math.log1p(value) for value in surrounding_cluster_tam]
            ),
            "final_vs_society_score": pearson(final_scores, society_scores),
            "final_vs_school_score": pearson(final_scores, school_scores),
            "final_vs_market_score": pearson(final_scores, market_scores),
            "final_vs_sez_workplace_score": pearson(final_scores, sez_scores),
        },
        "risk_checks": {
            "high_score_low_residential_count": len(high_score_low_residential),
            "high_score_low_residential_examples": high_score_low_residential[:20],
            "no_direct_but_cluster_supported_examples": no_direct_cluster_supported,
        },
    }


def summarize(records):
    return {
        "record_count": len(records),
        "tier_counts": dict(Counter(record["affluence_tier"] for record in records)),
        "spatial_relation_counts": dict(Counter(record["spatial_relation"] for record in records)),
        "score_stats": {
            "min": min(record["final_affluence_score"] for record in records),
            "median": quantile([record["final_affluence_score"] for record in records], 50),
            "p75": quantile([record["final_affluence_score"] for record in records], 75),
            "max": max(record["final_affluence_score"] for record in records),
            "mean": float(np.mean([record["final_affluence_score"] for record in records])),
        },
        "tam_totals": {
            "direct_family_tam": sum(record["tam"]["direct_family_tam"] for record in records),
            "society_cluster_tam_weighted": sum(
                record["tam"]["society_cluster_tam_weighted"] for record in records
            ),
            "surrounding_affluent_cluster_tam_weighted": sum(
                record["tam"]["surrounding_affluent_cluster_tam_weighted"] for record in records
            ),
            "estimated_wealthy_school_children": sum(
                record["tam"]["estimated_wealthy_school_children"] for record in records
            ),
        },
    }


def markdown_report(results):
    moran_rows = []
    for field, payload in results["morans_i"].items():
        moran_rows.append(
            "| {field} | {i:.4f} | {p} | {meaning} |".format(
                field=field,
                i=payload["morans_i"],
                p=(
                    "NA"
                    if payload["permutation_test"]["p_value_two_sided"] is None
                    else f"{payload['permutation_test']['p_value_two_sided']:.4f}"
                ),
                meaning=payload["interpretation"],
            )
        )

    coverage = results["model_diagnostics"]["coverage"]
    correlations = results["model_diagnostics"]["correlations"]
    risks = results["model_diagnostics"]["risk_checks"]
    spatial = results["spatial_buckets"]
    summary = results["summary"]

    risk_examples = "\n".join(
        f"- #{item['rank']} {item['name']} ({item['hex_id']}): "
        f"score {item['final_affluence_score']:.1f}, society {item['society_score']:.2f}, "
        f"cluster {item['society_cluster_score']:.2f}, direct TAM {item['direct_family_tam']:.0f}"
        for item in risks["high_score_low_residential_examples"][:10]
    )
    if not risk_examples:
        risk_examples = "- None."

    cluster_examples = "\n".join(
        f"- #{item['rank']} {item['name']} ({item['hex_id']}): "
        f"score {item['final_affluence_score']:.1f}, cluster score {item['society_cluster_score']:.2f}, "
        f"cluster TAM {item['society_cluster_tam_weighted']:.0f}"
        for item in risks["no_direct_but_cluster_supported_examples"][:10]
    )
    if not cluster_examples:
        cluster_examples = "- None."

    return f"""# Stage 2 Spatial Diagnostics and Model Checks

Generated after the latest Stage 2 rerun.

## Summary

- Hex records: {summary['record_count']}
- Final score median: {summary['score_stats']['median']:.2f}
- Final score max: {summary['score_stats']['max']:.2f}
- Direct family TAM total: {summary['tam_totals']['direct_family_tam']:.0f}
- Society cluster TAM weighted total: {summary['tam_totals']['society_cluster_tam_weighted']:.0f}
- Surrounding affluent cluster TAM weighted total: {summary['tam_totals']['surrounding_affluent_cluster_tam_weighted']:.0f}

## Moran's I

Moran's I tests whether high or low values cluster spatially. Positive values mean similar values tend to touch each other.

| Field | Moran's I | Permutation p-value | Interpretation |
|---|---:|---:|---|
{chr(10).join(moran_rows)}

## Spatial Buckets

- High-high cluster hexes: {spatial['bucket_counts'].get('high_high', 0)}
- High-low possible islands: {spatial['bucket_counts'].get('high_low', 0)}
- Low-high possible under-scored neighbors: {spatial['bucket_counts'].get('low_high', 0)}
- Low-low weak-evidence clusters: {spatial['bucket_counts'].get('low_low', 0)}
- Mixed/transition hexes: {spatial['bucket_counts'].get('mixed', 0)}

## Internal Model Checks

There is no external ground-truth affluent-family label in the workspace, so true predictive accuracy cannot be computed. These checks measure internal validity and face-validity risk.

- Top 25 no-direct-society flags: {coverage['top25_no_direct_society_tam']}
- Top 50 no-direct-society flags: {coverage['top50_no_direct_society_tam']}
- Top 100 no-direct-society flags: {coverage['top100_no_direct_society_tam']}
- Bottom 100 no-direct-society flags: {coverage['bottom100_no_direct_society_tam']}
- Top 50 with society evidence: {coverage['top50_with_society_evidence']} / 50
- Top 50 with school evidence: {coverage['top50_with_school_evidence']} / 50
- Top 50 with hospital evidence: {coverage['top50_with_hospital_evidence']} / 50

## Correlation Checks

- Final score vs log direct family TAM: {correlations['final_vs_log1p_direct_family_tam']:.3f}
- Final score vs log society cluster TAM: {correlations['final_vs_log1p_society_cluster_tam_weighted']:.3f}
- Final score vs log surrounding affluent cluster TAM: {correlations['final_vs_log1p_surrounding_affluent_cluster_tam_weighted']:.3f}
- Final score vs society score: {correlations['final_vs_society_score']:.3f}
- Final score vs school score: {correlations['final_vs_school_score']:.3f}
- Final score vs market score: {correlations['final_vs_market_score']:.3f}
- Final score vs SEZ score: {correlations['final_vs_sez_workplace_score']:.3f}

## Risk Checks

High-score but weak residential evidence count: {risks['high_score_low_residential_count']}

{risk_examples}

No-direct-TAM but cluster-supported examples:

{cluster_examples}

## Inference

If Moran's I is positive and statistically significant for final score and society score, the model is detecting spatially coherent affluent clusters rather than random isolated winners. If the SEZ correlation remains much lower than the society correlation, the workplace layer is not dominating the residential wealth result.

The model still should not be called "accurate" in the supervised ML sense until we add ground-truth validation labels, such as manually verified affluent-family zones, school enrollment catchments, household income proxies, or transaction-level premium residential validation.
"""


def interpretation(moran_i, p_value):
    if moran_i is None:
        return "not computable"
    if moran_i > 0.45 and p_value is not None and p_value <= 0.05:
        return "strong positive clustering"
    if moran_i > 0.25 and p_value is not None and p_value <= 0.05:
        return "moderate positive clustering"
    if moran_i > 0.10 and p_value is not None and p_value <= 0.05:
        return "weak positive clustering"
    if moran_i < -0.10 and p_value is not None and p_value <= 0.05:
        return "negative spatial dispersion"
    return "not statistically strong"


def main():
    records = load_records()
    hex_ids = [record["hex_id"] for record in records]
    neighbors = adjacency(hex_ids)
    record_by_hex = {record["hex_id"]: record for record in records}

    fields = {
        "final_affluence_score": lambda record: record["final_affluence_score"],
        "base_affluence_score": lambda record: record["base_affluence_score"],
        "society_score": lambda record: record["component_scores"]["society_score"],
        "society_cluster_score": lambda record: record["component_scores"]["society_cluster_score"],
        "direct_family_tam": lambda record: record["tam"]["direct_family_tam"],
        "society_cluster_tam_weighted": lambda record: record["tam"][
            "society_cluster_tam_weighted"
        ],
    }

    moran_results = {}
    for name, getter in fields.items():
        values_by_hex = {hex_id: getter(record_by_hex[hex_id]) for hex_id in hex_ids}
        observed = morans_i(values_by_hex, neighbors)
        permutation = permutation_test(values_by_hex, neighbors, observed)
        p_value = permutation["p_value_two_sided"]
        moran_results[name] = {
            "morans_i": observed,
            "permutation_test": permutation,
            "interpretation": interpretation(observed, p_value),
        }

    results = {
        "source": str(MASTER_JSON),
        "summary": summarize(records),
        "morans_i": moran_results,
        "spatial_buckets": classify_spatial_buckets(records, neighbors),
        "model_diagnostics": model_diagnostics(records),
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w") as f:
        json.dump(results, f, indent=2)
    OUTPUT_MD.write_text(markdown_report(results))
    print(f"Wrote {OUTPUT_JSON}")
    print(f"Wrote {OUTPUT_MD}")


if __name__ == "__main__":
    main()
