"""Contradiction, orphan, staleness, and redundancy detection.

Per ARCH-ORG-001: integrity logic lives here, raw queries in db.py.
Per ARCH-DI-001: receives db connection via constructor injection.
Per PY-ASYNC-001: all operations are async.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writ.graph.db import FalkorDBLiteConnection

from writ.graph.schema import REDUNDANCY_SIMILARITY_THRESHOLD


class IntegrityChecker:
    """Runs integrity checks against the rule graph."""

    def __init__(self, db: "FalkorDBLiteConnection") -> None:
        self._db = db

    async def detect_conflicts(self) -> list[dict]:
        """Find all rule pairs connected by CONFLICTS_WITH edges."""
        query = """
            MATCH (a:Rule)-[:CONFLICTS_WITH]->(b:Rule)
            WHERE a.rule_id < b.rule_id
            RETURN a.rule_id AS rule_a, b.rule_id AS rule_b
            ORDER BY rule_a
        """
        return self._db._execute_query(query)

    async def detect_orphans(self) -> list[str]:
        """Find rules with zero edges (unreachable by traversal)."""
        query = """
            MATCH (r:Rule)
            WHERE NOT (r)--()
            RETURN r.rule_id AS rule_id
            ORDER BY rule_id
        """
        return [row["rule_id"] for row in self._db._execute_query(query)]

    async def detect_stale(self) -> list[dict]:
        """Find rules past their staleness window."""
        today = date.today()
        query = """
            MATCH (r:Rule)
            WHERE r.last_validated IS NOT NULL
                AND r.staleness_window IS NOT NULL
            RETURN r.rule_id AS rule_id,
                   r.last_validated AS last_validated,
                   r.staleness_window AS staleness_window
        """
        stale: list[dict] = []
        for row in self._db._execute_query(query):
            last_val = row["last_validated"]
            window = row["staleness_window"]
            if isinstance(last_val, str):
                last_val = date.fromisoformat(last_val)
            expiry = last_val + timedelta(days=int(window))
            if expiry < today:
                stale.append({
                    "rule_id": row["rule_id"],
                    "last_validated": str(last_val),
                    "expired_on": str(expiry),
                })
        return stale

    async def detect_redundant(self) -> list[dict]:
        """Find rule pairs with near-identical trigger+statement text.

        Uses embedding cosine similarity. Requires sentence-transformers.
        """
        query = """
            MATCH (r:Rule)
            WHERE r.mandatory IS NULL OR r.mandatory = false
            RETURN r.rule_id AS rule_id,
                   r.trigger AS trigger,
                   r.statement AS statement
        """
        rules = self._db._execute_query(query)

        if len(rules) < 2:
            return []

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            # Approach C (Finding D): sentence-transformers moved out
            # of core deps. The redundancy check is opt-in by way of
            # this dependency. Returning [] here would silently degrade
            # into output indistinguishable from "no redundancies
            # found", which is the bug class fixed in commit dae679a
            # for the ONNX fallback. Raise with an actionable message
            # naming the cause, the [fallback] install command, and the
            # skip_redundancy=True opt-out for callers that intentionally
            # want to exclude this check (the integrity benchmark uses
            # this opt-out, for example).
            raise RuntimeError(
                "Redundancy check requires the sentence-transformers "
                f"library, which could not be imported ({type(exc).__name__}: "
                f"{exc}). "
                "Production installs deliberately exclude this library "
                "(see pyproject.toml: it lives in the [fallback] extras "
                "group, not core dependencies). To enable redundancy "
                "detection, run `pip install -e '.[fallback]'` and "
                "re-run the check. To intentionally exclude redundancy "
                "from an integrity scan (e.g., for benchmarking), pass "
                "skip_redundancy=True to run_all_checks()."
            ) from exc

        model = SentenceTransformer("all-MiniLM-L6-v2")
        texts = [f"{r['trigger']} {r['statement']}" for r in rules]
        embeddings = model.encode(texts, normalize_embeddings=True)

        redundant: list[dict] = []
        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                similarity = float(embeddings[i] @ embeddings[j])
                if similarity >= REDUNDANCY_SIMILARITY_THRESHOLD:
                    redundant.append({
                        "rule_a": rules[i]["rule_id"],
                        "rule_b": rules[j]["rule_id"],
                        "similarity": round(similarity, 4),
                    })
        return redundant

    async def detect_confidence_defaults(self) -> list[str]:
        """List rules still at migration default confidence."""
        query = """
            MATCH (r:Rule)
            WHERE r.confidence = 'production-validated'
            RETURN r.rule_id AS rule_id
            ORDER BY rule_id
        """
        return [row["rule_id"] for row in self._db._execute_query(query)]

    async def check_query_rule_ratio(self, query_count: int) -> dict | None:
        """Warn if ground-truth query-to-rule ratio drops below 1:10."""
        query = "MATCH (r:Rule) WHERE r.mandatory IS NULL OR r.mandatory = false RETURN count(r) AS count"
        rows = self._db._execute_query(query)
        rule_count = rows[0]["count"] if rows else 0

        ratio_threshold = 10
        if rule_count > 0 and query_count * ratio_threshold < rule_count:
            return {
                "rule_count": rule_count,
                "query_count": query_count,
                "required_queries": rule_count // ratio_threshold,
                "message": f"Query set covers {query_count}/{rule_count} rules "
                           f"(need at least {rule_count // ratio_threshold} queries for 1:{ratio_threshold} ratio)",
            }
        return None

    async def check_unreviewed_count(
        self,
        warning_percentage: float = 0.10,
        warning_floor: int = 5,
    ) -> dict | None:
        """Warn if unreviewed AI-provisional rules exceed threshold.

        Threshold: max(warning_floor, warning_percentage * total_rules).
        Returns warning dict if exceeded, None otherwise.
        """
        total_query = "MATCH (r:Rule) RETURN count(r) AS total"
        unreviewed_query = """
            MATCH (r:Rule)
            WHERE r.authority = 'ai-provisional'
            RETURN count(r) AS unreviewed
        """
        total_rows = self._db._execute_query(total_query)
        total = total_rows[0]["total"] if total_rows else 0

        unreviewed_rows = self._db._execute_query(unreviewed_query)
        unreviewed = unreviewed_rows[0]["unreviewed"] if unreviewed_rows else 0

        if unreviewed == 0:
            return None

        threshold = max(warning_floor, int(warning_percentage * total))
        if unreviewed >= threshold:
            return {
                "unreviewed": unreviewed,
                "total": total,
                "threshold": threshold,
                "message": f"{unreviewed} unreviewed AI-provisional rules "
                           f"(threshold: {threshold})",
            }
        return None

    async def detect_frequency_stale(self, window_days: int = 90) -> list[dict]:
        """Find rules with zero frequency over rolling window.

        Rules where (times_seen_positive + times_seen_negative) == 0
        AND (last_seen is NULL OR last_seen < now - window_days).
        Supplements the existing staleness_window / last_validated check.
        """
        cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
        query = """
            MATCH (r:Rule)
            WHERE (coalesce(r.times_seen_positive, 0) + coalesce(r.times_seen_negative, 0)) = 0
              AND (r.last_seen IS NULL OR r.last_seen < $cutoff)
            RETURN r.rule_id AS rule_id, r.last_seen AS last_seen
            ORDER BY rule_id
        """
        return self._db._execute_query(query, {"cutoff": cutoff})

    async def detect_graduation_flags(self) -> list[dict]:
        """Find rules that reached graduation threshold with ratio below minimum.

        These rules need human review per evolution plan Phase 4c.
        """
        from writ.frequency import (
            DEFAULT_GRADUATION_RATIO_MIN,
            DEFAULT_GRADUATION_THRESHOLD,
            evaluate_graduation,
        )

        query = """
            MATCH (r:Rule)
            WHERE (coalesce(r.times_seen_positive, 0) + coalesce(r.times_seen_negative, 0))
                  >= $threshold
            RETURN r.rule_id AS rule_id,
                   coalesce(r.times_seen_positive, 0) AS pos,
                   coalesce(r.times_seen_negative, 0) AS neg
        """
        records = self._db._execute_query(
            query, {"threshold": DEFAULT_GRADUATION_THRESHOLD},
        )

        flagged: list[dict] = []
        for rec in records:
            grad = evaluate_graduation(
                rec["pos"], rec["neg"],
                DEFAULT_GRADUATION_THRESHOLD,
                DEFAULT_GRADUATION_RATIO_MIN,
            )
            if grad.flagged:
                flagged.append({
                    "rule_id": rec["rule_id"],
                    "ratio": round(grad.ratio, 4),
                    "n": grad.n,
                })
        return flagged

    async def run_all_checks(self, skip_redundancy: bool = False) -> dict:
        """Run all integrity checks. Returns findings dict.

        Returns exit_code: 0 if clean, 1 if any findings.
        """
        findings: dict = {
            "conflicts": await self.detect_conflicts(),
            "orphans": await self.detect_orphans(),
            "stale": await self.detect_stale(),
        }

        if not skip_redundancy:
            try:
                findings["redundant"] = await self.detect_redundant()
            except RuntimeError as exc:
                # detect_redundant() raises when sentence-transformers
                # is not installed. Catch here so the other four checks
                # (conflicts, orphans, stale, confidence-defaults) still
                # complete and report; surface the missing-dep state via
                # a separate key the caller (writ validate) can print
                # explicitly. exit_code below excludes this key on
                # purpose: "we could not run the check" is informational,
                # not a finding.
                findings["redundant"] = []
                findings["redundancy_unavailable"] = str(exc)
        else:
            findings["redundant"] = []

        findings["unreviewed"] = await self.check_unreviewed_count()
        findings["frequency_stale"] = await self.detect_frequency_stale()
        findings["graduation_flags"] = await self.detect_graduation_flags()

        has_issues = any(
            findings[k] for k in ("conflicts", "orphans", "stale", "redundant")
        )
        findings["exit_code"] = 1 if has_issues else 0
        return findings
