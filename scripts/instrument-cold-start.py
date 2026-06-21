#!/usr/bin/env python3
"""Per-stage cold-start instrumentation for build_pipeline().

Runs build_pipeline() three times against the live 276-rule corpus
and reports per-stage timings: graph queries, BM25 build, embedding
model load, bulk encode, HNSW (load-from-cache vs build vs save),
adjacency cache build, abstractions load.

Read-only -- does not modify any production code path. Implements
the instrumentation by monkey-patching the inner constructors and
methods that build_pipeline() calls, recording perf_counter()
deltas to a per-run dict.

Usage:
    python3 scripts/instrument-cold-start.py [--runs N] [--clear-hnsw-cache]

Output: a per-stage timing table per run plus an aggregated row.
Use --clear-hnsw-cache before run 1 to force a cold-cold first run;
runs 2 and 3 then exercise the warm-cache path.

KNOWN MEASUREMENT ARTIFACT (read before trusting iteration 1 numbers).
The monkey-patches installed by install_patches() close over the
per-iteration `record` dict. Subsequent install_patches() calls do
not REMOVE prior patches; they stack on top, so on iteration N the
wrapper chain is wrap_N -> wrap_{N-1} -> ... -> wrap_1 -> real. When
the real method fires, each surviving wrap's closure records into
its captured `record`. The dict returned for iteration 1 therefore
accumulates time from iterations 1, 2, and 3 by the time the table
is printed; the dict for iteration 2 accumulates iterations 2 and 3;
only iteration N (the latest) is clean.

The `total` field (measured outside the wrapper chain with a fresh
time.perf_counter()) is correct for every iteration.

If you only need the substantive timings, trust the LAST iteration's
per-stage row and the `total` field for all iterations. If you want
clean per-iteration breakdowns, run with --runs 1 multiple times
between fresh script invocations, or rewrite install_patches() to
keep a stack of patched/un-patched states and properly restore on
each iteration.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from writ.config import (
    get_hnsw_cache_dir,
    get_falkordb_path,
    get_falkordb_graph,
    get_falkordb_module,
    get_redis_bin,
)
from writ.graph.db import FalkorDBLiteConnection
from writ.retrieval import embeddings as embeddings_mod
from writ.retrieval import keyword as keyword_mod
from writ.retrieval import traversal as traversal_mod
from writ.retrieval.pipeline import build_pipeline


@contextmanager
def timed(record: dict[str, float], key: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record[key] = record.get(key, 0.0) + (time.perf_counter() - t0)


def install_patches(record: dict[str, float]) -> None:
    """Monkey-patch the inner build steps to record per-stage timings."""

    # Embedding model load (ONNX preferred; SentenceTransformer fallback).
    real_onnx_init = embeddings_mod.OnnxEmbeddingModel.__init__

    def patched_onnx_init(self, *args, **kwargs):
        with timed(record, "embedding_model_load"):
            real_onnx_init(self, *args, **kwargs)

    embeddings_mod.OnnxEmbeddingModel.__init__ = patched_onnx_init

    # Bulk encode (the actual embedding compute over all rule texts).
    real_encode_batch = embeddings_mod.OnnxEmbeddingModel.encode_batch

    def patched_encode_batch(self, *args, **kwargs):
        with timed(record, "embedding_bulk_encode"):
            return real_encode_batch(self, *args, **kwargs)

    embeddings_mod.OnnxEmbeddingModel.encode_batch = patched_encode_batch

    # KeywordIndex.build (BM25/Tantivy index construction).
    real_kw_build = keyword_mod.KeywordIndex.build

    def patched_kw_build(self, *args, **kwargs):
        with timed(record, "bm25_index_build"):
            return real_kw_build(self, *args, **kwargs)

    keyword_mod.KeywordIndex.build = patched_kw_build

    # HnswlibStore: load_index, build_index, save_index.
    real_hnsw_load = embeddings_mod.HnswlibStore.load_index

    def patched_hnsw_load(self, *args, **kwargs):
        with timed(record, "hnsw_load_from_cache"):
            return real_hnsw_load(self, *args, **kwargs)

    embeddings_mod.HnswlibStore.load_index = patched_hnsw_load

    real_hnsw_build = embeddings_mod.HnswlibStore.build_index

    def patched_hnsw_build(self, *args, **kwargs):
        with timed(record, "hnsw_index_build"):
            return real_hnsw_build(self, *args, **kwargs)

    embeddings_mod.HnswlibStore.build_index = patched_hnsw_build

    real_hnsw_save = embeddings_mod.HnswlibStore.save_index

    def patched_hnsw_save(self, *args, **kwargs):
        with timed(record, "hnsw_save_to_cache"):
            return real_hnsw_save(self, *args, **kwargs)

    embeddings_mod.HnswlibStore.save_index = patched_hnsw_save

    # AdjacencyCache.build_from_db (Stage 4 graph traversal cache).
    real_adj_build = traversal_mod.AdjacencyCache.build_from_db

    async def patched_adj_build(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return await real_adj_build(self, *args, **kwargs)
        finally:
            record["adjacency_cache_build"] = record.get("adjacency_cache_build", 0.0) + (
                time.perf_counter() - t0
            )

    traversal_mod.AdjacencyCache.build_from_db = patched_adj_build


async def run_one(db: FalkorDBLiteConnection, run_index: int) -> dict[str, float]:
    record: dict[str, float] = {}
    install_patches(record)

    t_total_start = time.perf_counter()
    await build_pipeline(db)
    record["total"] = time.perf_counter() - t_total_start

    return record


def print_table(runs: list[dict[str, float]]) -> None:
    stages = [
        "embedding_model_load",
        "embedding_bulk_encode",
        "bm25_index_build",
        "hnsw_load_from_cache",
        "hnsw_index_build",
        "hnsw_save_to_cache",
        "adjacency_cache_build",
    ]
    headers = ["stage"] + [f"run {i + 1}" for i in range(len(runs))]
    rows = []
    for stage in stages:
        row = [stage]
        for r in runs:
            v = r.get(stage)
            row.append("--" if v is None else f"{v:.3f}s")
        rows.append(row)

    accounted = []
    for r in runs:
        accounted.append(sum(r.get(s, 0.0) for s in stages))
    totals = [r.get("total", 0.0) for r in runs]
    unaccounted = [t - a for t, a in zip(totals, accounted)]

    rows.append(["(other / graph queries)"] + [f"{u:.3f}s" for u in unaccounted])
    rows.append(["total"] + [f"{t:.3f}s" for t in totals])

    col_widths = [max(len(str(row[i])) for row in rows + [headers]) for i in range(len(headers))]

    def fmt_row(row):
        return "  ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(row))

    print()
    print(fmt_row(headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt_row(row))
    print()

    # HNSW fraction-of-cold-start summary (the load-bearing number).
    hnsw_costs = [r.get("hnsw_index_build", 0.0) + r.get("hnsw_save_to_cache", 0.0) for r in runs]
    print("HNSW build+save as fraction of total:")
    for i, (h, t) in enumerate(zip(hnsw_costs, totals)):
        pct = (h / t * 100.0) if t else 0.0
        print(f"  run {i + 1}: {h:.3f}s / {t:.3f}s = {pct:.1f}%")


async def main(args: argparse.Namespace) -> None:
    if args.clear_hnsw_cache:
        cache_dir = get_hnsw_cache_dir()
        if Path(cache_dir).exists():
            shutil.rmtree(cache_dir)
            print(f"Cleared HNSW cache at {cache_dir}")

    conn = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    count = await conn.count_rules()
    if count == 0:
        print("ERROR: Graph has no rules. Run `writ import-markdown` first.")
        await conn.close()
        return
    print(f"Corpus: {count} rules. Running {args.runs} iterations of build_pipeline().")

    runs: list[dict[str, float]] = []
    for i in range(args.runs):
        print(f"  iteration {i + 1}/{args.runs}...", flush=True)
        r = await run_one(conn, i)
        runs.append(r)

    await conn.close()
    print_table(runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Iterations of build_pipeline() to time (default 3)")
    parser.add_argument(
        "--clear-hnsw-cache",
        action="store_true",
        help="Delete the HNSW persistence cache before run 1 to force cold-cold",
    )
    asyncio.run(main(parser.parse_args()))
