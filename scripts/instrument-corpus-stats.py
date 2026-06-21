#!/usr/bin/env python3
"""Item 2 (live-vs-synthetic latency gap) hypothesis tests.

Compares the real 276-rule corpus to the synthetic generator on four
hypotheses for why real corpus is harder to rank at matched scale:

  H1. Text length: real rules longer than synthetic.
  H2. Edge density: real graph has more edges per node than synthetic.
  H3. BM25 candidate-set size: real queries surface more candidates.
  H4. Intra-domain vocabulary overlap: real domain partitions have
      semantically similar rules, while synthetic domains have clean
      disjoint vocabularies (the headline hypothesis from the design
      discussion).

Read-only against the live corpus and the in-repo synthetic generator.
No side effects.
"""
from __future__ import annotations

import asyncio
import statistics
from collections import defaultdict

import numpy as np

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection
from writ.retrieval.embeddings import DEFAULT_ONNX_DIR, OnnxEmbeddingModel
from writ.retrieval.keyword import KeywordIndex
from writ.retrieval.pipeline import build_pipeline


def _rule_text(rule: dict) -> str:
    return f"{rule.get('trigger', '')} {rule.get('statement', '')}"


def _full_rendered_text(rule: dict) -> str:
    parts = [
        rule.get("trigger", ""),
        rule.get("statement", ""),
        rule.get("violation", ""),
        rule.get("pass_example", ""),
        rule.get("rationale", ""),
    ]
    return " ".join(p for p in parts if p)


def _generate_synthetic_rules(n: int) -> list[dict]:
    """Mirror the synthetic-rule pattern used by benchmarks/scale_benchmark.py
    so the comparison is against the actual generator, not an idealized model.

    Domain prefixes produce disjoint per-domain vocabularies by design;
    each rule's text follows a deterministic template.
    """
    domains = [
        "Security", "Architecture", "Performance", "Testing", "ErrorHandling",
        "Documentation", "Scaling", "ApiDesign", "CodeQuality", "DryPrinciple",
        "SolidPrinciple", "Process", "Framework", "Methodology", "Enforcement",
        "DataValidation", "ConcurrencyControl",
    ]
    rules = []
    for i in range(n):
        domain = domains[i % len(domains)]
        rules.append({
            "rule_id": f"SYNTH-{domain.upper()}-{i:04d}",
            "domain": domain,
            "trigger": f"When implementing {domain.lower()} concern number {i}.",
            "statement": (
                f"Apply the {domain.lower()} rule {i} to the implementation. "
                f"Follow the {domain.lower()} pattern."
            ),
            "violation": f"Violating {domain.lower()} rule {i}.",
            "pass_example": f"Passing example for {domain.lower()} rule {i}.",
            "rationale": f"Reason for {domain.lower()} rule {i}.",
        })
    return rules


async def _load_real_corpus(db) -> list[dict]:
    query = """
        MATCH (r:Rule)
        WHERE r.mandatory IS NULL OR r.mandatory = false
        RETURN r
    """
    rows = db._execute_query(query)
    return [row["r"] for row in rows]


async def _count_edges(db) -> tuple[int, int]:
    edge_query = "MATCH ()-[r]->() RETURN count(r) AS edges"
    node_query = "MATCH (r:Rule) RETURN count(r) AS nodes"
    e = db._execute_query(edge_query)[0]["edges"]
    n = db._execute_query(node_query)[0]["nodes"]
    return e, n


def _h1_text_length(real: list[dict], synth: list[dict]) -> None:
    print("\n== H1: Text length per rule ==")
    for label, rules in [("real", real), ("synthetic", synth)]:
        trig_stmt = [len(_rule_text(r)) for r in rules]
        full = [len(_full_rendered_text(r)) for r in rules]
        print(
            f"  {label:9s}  N={len(rules):4d}  trigger+statement  "
            f"median={statistics.median(trig_stmt):4.0f} chars  "
            f"mean={statistics.mean(trig_stmt):4.0f}  "
            f"max={max(trig_stmt)}"
        )
        print(
            f"  {label:9s}  N={len(rules):4d}  full rendered      "
            f"median={statistics.median(full):4.0f} chars  "
            f"mean={statistics.mean(full):4.0f}  "
            f"max={max(full)}"
        )


async def _h2_edge_density(db, synth_n: int) -> None:
    print("\n== H2: Edge density (real graph; synthetic skeleton has zero) ==")
    edges, nodes = await _count_edges(db)
    print(f"  real       {nodes} nodes, {edges} edges, "
          f"ratio={edges/max(nodes,1):.2f} edges/node")
    print(f"  synthetic  generated rules have no graph edges by construction "
          f"(scale_benchmark.py uses Rule nodes only, no RELATED_TO etc.)")


def _h3_bm25_candidate_sets(real: list[dict], synth: list[dict]) -> None:
    print("\n== H3: BM25 candidate-set size on test queries ==")
    queries = [
        "controller SQL query",
        "dependency injection",
        "async event loop blocking",
        "security authorization",
        "performance optimization",
    ]
    for label, rules in [("real", real), ("synthetic", synth)]:
        idx = KeywordIndex()
        idx.build(rules)
        sizes = [len(idx.search(q, limit=50)) for q in queries]
        print(
            f"  {label:9s}  per-query candidates returned (top_k=50): "
            f"median={statistics.median(sizes):2.0f}  "
            f"mean={statistics.mean(sizes):4.1f}  "
            f"samples={sizes}"
        )


def _h4_intra_domain_similarity(real: list[dict], synth: list[dict]) -> None:
    print("\n== H4: Intra-domain pairwise cosine similarity ==")
    model = OnnxEmbeddingModel(DEFAULT_ONNX_DIR)
    for label, rules in [("real", real), ("synthetic", synth)]:
        by_domain: dict[str, list[dict]] = defaultdict(list)
        for r in rules:
            by_domain[r.get("domain", "")].append(r)
        all_pairwise: list[float] = []
        per_domain: list[tuple[str, int, float]] = []
        for domain, drules in by_domain.items():
            if len(drules) < 2:
                continue
            texts = [_rule_text(r) for r in drules]
            embs = np.asarray(model.encode_batch(texts), dtype=np.float32)
            sims: list[float] = []
            for i in range(len(embs)):
                for j in range(i + 1, len(embs)):
                    sims.append(float(embs[i] @ embs[j]))
            per_domain.append((domain, len(drules), statistics.median(sims)))
            all_pairwise.extend(sims)
        per_domain.sort(key=lambda x: -x[2])
        print(f"  {label}:")
        for domain, n, med in per_domain[:6]:
            print(f"    {domain[:32]:32s}  n={n:3d}  median_cosine={med:.3f}")
        print(
            f"    ...  overall (all domains pooled): "
            f"median={statistics.median(all_pairwise):.3f}  "
            f"p75={sorted(all_pairwise)[int(len(all_pairwise)*0.75)]:.3f}  "
            f"max={max(all_pairwise):.3f}"
        )


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        real = await _load_real_corpus(db)
        synth = _generate_synthetic_rules(len(real))
        print(f"Real corpus: {len(real)} domain rules")
        print(f"Synthetic comparison: {len(synth)} rules at matched scale")
        _h1_text_length(real, synth)
        await _h2_edge_density(db, len(synth))
        _h3_bm25_candidate_sets(real, synth)
        _h4_intra_domain_similarity(real, synth)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
