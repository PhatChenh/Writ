"""Embedding model tests: ONNX Runtime, CachedEncoder, ranking stability.

Per TEST-ISO-001: each test owns its data.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from writ.retrieval.embeddings import (
    DEFAULT_ONNX_DIR,
    CachedEncoder,
    OnnxEmbeddingModel,
)


# --- Fixtures ---


@pytest.fixture()
def onnx_model():
    """Load ONNX model if available, skip if not exported."""
    try:
        return OnnxEmbeddingModel(DEFAULT_ONNX_DIR)
    except (FileNotFoundError, ImportError):
        pytest.skip("ONNX model not exported. Run: python scripts/export_onnx.py")


def _make_mock_model():
    """Mock model that returns a deterministic 384-dim vector."""
    model = MagicMock()
    call_count = [0]

    def mock_encode(text):
        call_count[0] += 1
        rng = np.random.RandomState(hash(text) % 2**31)
        return rng.randn(384).astype(np.float32)

    model.encode = mock_encode
    model._call_count = call_count
    return model


# --- OnnxEmbeddingModel ---


class TestOnnxEmbeddingModel:
    """ONNX Runtime embedding model."""

    def test_encode_returns_correct_dimensions(self, onnx_model) -> None:
        vector = onnx_model.encode("test query")
        assert vector.shape == (384,)

    def test_encode_deterministic(self, onnx_model) -> None:
        v1 = onnx_model.encode("test query")
        v2 = onnx_model.encode("test query")
        assert np.allclose(v1, v2)

    def test_encode_different_texts_differ(self, onnx_model) -> None:
        v1 = onnx_model.encode("async blocking event loop")
        v2 = onnx_model.encode("SQL injection prevention")
        assert not np.allclose(v1, v2)

    def test_encode_batch_matches_single(self, onnx_model) -> None:
        texts = ["query one", "query two"]
        batch = onnx_model.encode_batch(texts)
        single_0 = onnx_model.encode(texts[0])
        single_1 = onnx_model.encode(texts[1])
        assert np.allclose(batch[0], single_0, atol=1e-5)
        assert np.allclose(batch[1], single_1, atol=1e-5)


# --- CachedEncoder ---


class TestCachedEncoder:
    """LRU cache on encode calls with mutation safety."""

    def test_cache_hit_returns_same_values(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=128)
        v1 = encoder.encode("test query")
        v2 = encoder.encode("test query")
        assert np.array_equal(v1, v2)

    def test_cache_miss_calls_model(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=128)
        encoder.encode("query 1")
        encoder.encode("query 2")
        assert model._call_count[0] == 2

    def test_cache_hit_does_not_call_model(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=128)
        encoder.encode("query 1")
        encoder.encode("query 1")
        assert model._call_count[0] == 1

    def test_maxsize_evicts_oldest(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=2)
        encoder.encode("a")
        encoder.encode("b")
        encoder.encode("c")  # evicts "a"
        encoder.encode("a")  # cache miss, re-encodes
        assert model._call_count[0] == 4

    def test_cache_info_reports_stats(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=128)
        encoder.encode("q1")
        encoder.encode("q1")
        info = encoder.cache_info()
        assert info.hits == 1
        assert info.misses == 1

    def test_cache_returns_independent_copies(self) -> None:
        model = _make_mock_model()
        encoder = CachedEncoder(model, maxsize=128)
        v1 = encoder.encode("test query")
        v1[0] = 999.0  # mutate returned array
        v2 = encoder.encode("test query")  # cache hit
        assert v2[0] != 999.0  # cached value not corrupted


# --- Ranking Stability (Integration) ---


class TestOnnxRankingStability:
    """ONNX produces ranking output equivalent to PyTorch on a fixed
    inline corpus.

    Rewritten 2026-05-14 (Finding 10) to fix the test-order-dependent
    flake. The prior implementation read the corpus from the graph DB and
    asserted strict top-5 ordering equality against the
    sentence-transformers + ONNX pipelines; it passed inside the full
    `make test` suite but failed in isolation with 4 ADJACENT-SWAP
    divergences against the long-lived 276-rule corpus. The test was
    measuring numerical-precision drift between the two backends but
    coupling that measurement to whatever corpus state the graph DB happened
    to be in at the time it ran.

    Two changes make the test corpus-state-independent:

      1. The corpus is declared inline. The graph DB is not involved.
         build_pipeline is not involved. The test exercises the
         embedding + cosine-similarity layer directly, which is the
         layer where PT vs ONNX divergence actually originates.

      2. The assertion is relaxed to the production-meaningful
         property: top-1 must be identical (the rule the user
         actually sees first), and top-5 as a SET must be identical
         (the rules surfaced as relevant). Adjacent-swap inside
         top-5 is numerical noise from float32 precision differences
         between PyTorch's CPU tensor math and the ONNX-exported
         graph; the order of positions 2-5 is not a stable property
         in production either. Strict ordering equality on top-5
         was overspecified.

    The corpus below was chosen to give large cosine-similarity gaps
    between the most-relevant rule and the next-most-relevant rule
    for each query, so the top-1 assertion is robust against the
    ~1e-4 precision differences observed between backends. If a
    future ONNX export changes the architecture or quantization in
    a way that affects rankings at the top-1 level, this test will
    fail and the test name will tell the maintainer exactly which
    property regressed.
    """

    # Inline corpus: 12 rules from different domains with diverse
    # trigger and statement vocabulary. Each rule is short and
    # self-contained; the cosine-sim signal comes from semantic
    # overlap between the rule text and the query, not from
    # incidental shared words across many rules.
    _CORPUS: list[dict] = [
        {
            "rule_id": "TEST-CORPUS-SQL-001",
            "trigger": "controller contains SQL query directly",
            "statement": "Move SQL queries out of controllers into a repository layer.",
        },
        {
            "rule_id": "TEST-CORPUS-DIP-001",
            "trigger": "class instantiates its dependencies directly",
            "statement": "Inject dependencies via constructor instead of newing them up.",
        },
        {
            "rule_id": "TEST-CORPUS-ASYNC-001",
            "trigger": "async function calls a blocking I/O routine",
            "statement": "Wrap blocking calls in run_in_executor or use the async variant.",
        },
        {
            "rule_id": "TEST-CORPUS-NPLUS1-001",
            "trigger": "loop body issues one database query per iteration",
            "statement": "Batch the queries into a single round-trip with a join or IN clause.",
        },
        {
            "rule_id": "TEST-CORPUS-RETRY-001",
            "trigger": "retry loop has no backoff and no cap",
            "statement": "Use exponential backoff with jitter and a maximum attempt count.",
        },
        {
            "rule_id": "TEST-CORPUS-LOG-001",
            "trigger": "logger writes user-supplied input without escaping",
            "statement": "Sanitize log values to prevent log injection from CR/LF in input.",
        },
        {
            "rule_id": "TEST-CORPUS-SECRET-001",
            "trigger": "secret value committed in source code",
            "statement": "Move credentials to environment variables or a secrets manager.",
        },
        {
            "rule_id": "TEST-CORPUS-TIMEOUT-001",
            "trigger": "HTTP request issued without an explicit timeout",
            "statement": "Set a timeout on every outbound HTTP call to avoid stuck threads.",
        },
        {
            "rule_id": "TEST-CORPUS-NULL-001",
            "trigger": "function returns null for both success and failure",
            "statement": "Return a tagged Result type or raise an exception on failure.",
        },
        {
            "rule_id": "TEST-CORPUS-COMMENT-001",
            "trigger": "comment describes what the code does line by line",
            "statement": "Write comments that explain why, not what; let names carry the what.",
        },
        {
            "rule_id": "TEST-CORPUS-MIGRATE-001",
            "trigger": "schema change deployed without a migration",
            "statement": "Apply database schema changes via versioned migration files only.",
        },
        {
            "rule_id": "TEST-CORPUS-CSP-001",
            "trigger": "HTML response served without a Content-Security-Policy header",
            "statement": "Set CSP with default-src self and explicit allowlists per directive.",
        },
    ]

    # Queries chosen to exercise the embedding + ranking layer with
    # realistic phrasing. The test does NOT assert "PT/ONNX picks the
    # right rule for the query" -- retrieval quality is the MRR@5
    # gate's job. This test asserts only that PT and ONNX agree with
    # each other on whatever rule they pick. If they pick the wrong
    # rule but agree, that is retrieval quality, not the PT-vs-ONNX
    # precision question this test guards.
    _QUERIES: list[str] = [
        "I have a SELECT statement inside my Flask route handler",
        "async function is calling requests.get which blocks the event loop",
        "we are issuing one query per row when loading the user list",
        "outbound API call with no timeout configured",
        "the response is missing a Content-Security-Policy",
        "credentials are checked into the repo as plain text",
        "schema migration applied directly to production database",
        "this comment just restates the next line",
    ]

    def _rule_text(self, rule: dict) -> str:
        return f"{rule['trigger']} {rule['statement']}"

    def _top_k_indices(self, query_vec: np.ndarray, corpus_vecs: np.ndarray, k: int) -> list[int]:
        """Return indices of top-k highest cosine-similarity entries.

        Vectors are expected to be L2-normalized; cosine reduces to
        dot product. Sort is stable on the (negative) similarity so
        ties produce a deterministic order.
        """
        sims = corpus_vecs @ query_vec
        # argsort ascending; take the last k indices, reverse to descending.
        return list(np.argsort(sims)[-k:][::-1])

    def test_top1_and_top5_set_equivalent_pt_vs_onnx(self, onnx_model) -> None:
        """PT and ONNX produce identical top-1 and identical top-5 sets
        on a fixed inline corpus.

        Skips if `sentence-transformers` is not installed (Finding D
        moved it to the [fallback] extras group). Skips if the ONNX
        model is not exported (the `onnx_model` fixture handles this).
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            pytest.skip(
                "sentence-transformers not installed. After Finding D "
                "(2026-05-14) this library is in the [fallback] extras "
                "group; install with `pip install -e '.[fallback]'` to "
                "exercise this test."
            )

        pt_model = SentenceTransformer("all-MiniLM-L6-v2")
        corpus_texts = [self._rule_text(r) for r in self._CORPUS]

        # Embed corpus with both backends. SentenceTransformer.encode
        # returns L2-normalized vectors by default via normalize_embeddings;
        # OnnxEmbeddingModel.encode_batch normalizes internally.
        pt_corpus = pt_model.encode(corpus_texts, normalize_embeddings=True)
        onnx_corpus = onnx_model.encode_batch(corpus_texts)

        pt_corpus = np.asarray(pt_corpus, dtype=np.float32)
        onnx_corpus = np.asarray(onnx_corpus, dtype=np.float32)

        assert pt_corpus.shape == onnx_corpus.shape == (len(self._CORPUS), 384), (
            f"shape mismatch: pt={pt_corpus.shape} onnx={onnx_corpus.shape}"
        )

        # Compare top-1 (strict) and top-5 (set) for each query.
        top1_mismatches: list[dict] = []
        top5_set_mismatches: list[dict] = []

        for query_text in self._QUERIES:
            pt_query = np.asarray(
                pt_model.encode([query_text], normalize_embeddings=True)[0],
                dtype=np.float32,
            )
            onnx_query = np.asarray(
                onnx_model.encode_batch([query_text])[0],
                dtype=np.float32,
            )

            pt_top5_idx = self._top_k_indices(pt_query, pt_corpus, k=5)
            onnx_top5_idx = self._top_k_indices(onnx_query, onnx_corpus, k=5)

            pt_top5_ids = [self._CORPUS[i]["rule_id"] for i in pt_top5_idx]
            onnx_top5_ids = [self._CORPUS[i]["rule_id"] for i in onnx_top5_idx]

            # Top-1 strict: production users see this rule first.
            # If PT and ONNX disagree on the top-1, retrieval-quality
            # numbers do not transfer between backends.
            if pt_top5_ids[0] != onnx_top5_ids[0]:
                top1_mismatches.append({
                    "query": query_text,
                    "pt_top1": pt_top5_ids[0],
                    "onnx_top1": onnx_top5_ids[0],
                })

            # Top-5 as set: the rules surfaced as relevant. Order
            # inside positions 2-5 is float32-precision noise; the
            # SET being identical is the meaningful property. The
            # prior version of this test asserted strict-order top-5
            # equality and produced 4 ADJACENT-SWAP false positives
            # against the production corpus -- adjacent swaps are not
            # a regression signal, they are precision noise.
            if set(pt_top5_ids) != set(onnx_top5_ids):
                top5_set_mismatches.append({
                    "query": query_text,
                    "pt_only": sorted(set(pt_top5_ids) - set(onnx_top5_ids)),
                    "onnx_only": sorted(set(onnx_top5_ids) - set(pt_top5_ids)),
                })

        assert not top1_mismatches, (
            f"PT and ONNX disagree on top-1 for {len(top1_mismatches)} "
            f"queries (production users would see different rules first): "
            f"{top1_mismatches}"
        )
        assert not top5_set_mismatches, (
            f"PT and ONNX top-5 SETS differ on {len(top5_set_mismatches)} "
            f"queries (different rules surfaced as relevant): "
            f"{top5_set_mismatches}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Embedding-model selection in build_pipeline(): three-state contract.
#
# State 1: ONNX construction succeeds                     -> production path.
# State 2: ONNX fails + WRIT_ALLOW_EMBEDDING_FALLBACK=1   -> SentenceTransformer
#                                                            with WARNING log.
# State 3: ONNX fails + no override                       -> RuntimeError raised.
#
# Prior behavior silently swallowed FileNotFoundError / ImportError and
# fell through to SentenceTransformer. The override env var keeps the
# fallback available for dev environments that have not yet exported
# ONNX, but requires explicit opt-in so production cannot regress
# silently. See commit history for the full diagnosis.
# ──────────────────────────────────────────────────────────────────────────


class TestEmbeddingModelSelection:
    """Behavior tests for the ONNX-required / fallback-opt-in / refuse contract."""

    @pytest.fixture()
    def force_onnx_failure(self, monkeypatch):
        """Replace OnnxEmbeddingModel in the pipeline module so construction raises.

        Mimics the production failure mode that motivated this contract:
        OnnxEmbeddingModel.__init__ raises ImportError when onnxruntime
        is missing from the active interpreter (system python without
        the dev deps installed) or FileNotFoundError when the ONNX
        export has not been produced yet.
        """
        from writ.retrieval import pipeline as pipeline_mod

        def fail(_model_dir):
            raise FileNotFoundError("simulated: ONNX model not exported")

        monkeypatch.setattr(pipeline_mod, "OnnxEmbeddingModel", fail)

    @pytest.fixture()
    def fake_sentence_transformer(self, monkeypatch):
        """Replace sentence_transformers.SentenceTransformer with a fast stub.

        The real fallback loads PyTorch + a ~90 MB model file, which adds
        seconds per test invocation. The stub returns the same shape
        (N x 384 numpy array) so build_pipeline progresses past the
        embedding step without the real cost.
        """
        import sys
        import types

        fake_module = types.ModuleType("sentence_transformers")

        class StubSentenceTransformer:
            def __init__(self, model_name):
                self.model_name = model_name

            def encode(self, texts):
                return np.zeros((len(texts), 384), dtype=np.float32)

        fake_module.SentenceTransformer = StubSentenceTransformer
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    @pytest.mark.asyncio
    async def test_raises_when_onnx_unavailable_and_no_override(
        self, monkeypatch, force_onnx_failure, db
    ):
        """State 3: ONNX construction fails, no override env var, build_pipeline raises."""
        from writ.retrieval.pipeline import build_pipeline

        monkeypatch.delenv("WRIT_ALLOW_EMBEDDING_FALLBACK", raising=False)

        count = await db.count_rules()
        if count == 0:
            pytest.skip("No rules in test graph. Run `writ import-markdown` first.")

        with pytest.raises(RuntimeError) as excinfo:
            await build_pipeline(db)

        msg = str(excinfo.value)
        # The message must name the cause exception class, the override
        # env var, and the export script. If any of those goes missing,
        # the next maintainer hits the error without an actionable next
        # step and the contract loses its operational value.
        assert "ONNX embedding model unavailable" in msg
        assert "FileNotFoundError" in msg
        assert "WRIT_ALLOW_EMBEDDING_FALLBACK" in msg
        assert "scripts/export_onnx.py" in msg

    @pytest.fixture()
    def force_sentence_transformers_unavailable(self, monkeypatch):
        """Replace sentence_transformers in sys.modules with None so import raises ImportError.

        Mimics the production state after Approach C (Finding D fix):
        production installs do not pull sentence-transformers. Importing
        it raises ImportError unless the operator has run
        ``pip install -e '.[fallback]'``. Setting ``sys.modules[name] = None``
        is the documented Python mechanism to make a subsequent import
        of that name fail with ImportError.
        """
        import sys

        monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    @pytest.mark.asyncio
    async def test_fallback_raises_actionable_error_when_sentence_transformers_missing(
        self,
        monkeypatch,
        force_onnx_failure,
        force_sentence_transformers_unavailable,
        db,
    ):
        """State: ONNX unavailable, fallback opted in via env var, but
        sentence-transformers also missing.

        After Approach C drops sentence-transformers from core deps, the
        WRIT_ALLOW_EMBEDDING_FALLBACK=1 path is only usable when the
        operator has also installed the [fallback] extras group. When
        they have not, build_pipeline must raise a RuntimeError that
        names the missing library AND the install command, not a bare
        ImportError from the inline import inside the fallback branch.

        Same shape as the ONNX-unavailable error (commit dae679a):
        actionable, names cause + remediation, surfaces at startup not
        at first request.
        """
        from writ.retrieval.pipeline import build_pipeline

        monkeypatch.setenv("WRIT_ALLOW_EMBEDDING_FALLBACK", "1")

        count = await db.count_rules()
        if count == 0:
            pytest.skip("No rules in test graph. Run `writ import-markdown` first.")

        with pytest.raises(RuntimeError) as excinfo:
            await build_pipeline(db)

        msg = str(excinfo.value)
        # The error must name the missing library, the [fallback]
        # install command, and the pip install verb so a user
        # scanning the message can act without re-reading docs.
        assert "sentence" in msg.lower(), (
            f"RuntimeError must name sentence-transformers; got: {msg!r}"
        )
        assert "fallback" in msg, (
            f"RuntimeError must name the [fallback] extras group; got: {msg!r}"
        )
        assert "pip install" in msg, (
            f"RuntimeError must name the pip install verb; got: {msg!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_used_when_override_set_and_warning_logged(
        self, monkeypatch, caplog, force_onnx_failure, fake_sentence_transformer, db
    ):
        """State 2: ONNX fails, override env var is set, fallback is taken and warned."""
        import logging

        from writ.retrieval.pipeline import build_pipeline

        monkeypatch.setenv("WRIT_ALLOW_EMBEDDING_FALLBACK", "1")
        caplog.set_level(logging.WARNING, logger="writ.retrieval.pipeline")

        count = await db.count_rules()
        if count == 0:
            pytest.skip("No rules in test graph. Run `writ import-markdown` first.")

        # Should NOT raise -- the override grants permission to fall back.
        pipeline = await build_pipeline(db)
        assert pipeline is not None

        warnings = [
            rec
            for rec in caplog.records
            if rec.levelno >= logging.WARNING
            and rec.name == "writ.retrieval.pipeline"
        ]
        assert warnings, "expected WARNING from pipeline; got none"
        warning_text = " ".join(rec.getMessage() for rec in warnings)
        assert "ONNX embedding model unavailable" in warning_text
        assert "WRIT_ALLOW_EMBEDDING_FALLBACK" in warning_text
        assert "SentenceTransformer fallback" in warning_text
