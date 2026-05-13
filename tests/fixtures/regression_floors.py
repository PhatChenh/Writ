"""Regression floors for retrieval-quality gate metrics.

Canonical source of truth for the MRR@5 ambiguous-set floor and the
hit-rate floor across the full ground-truth corpus. Both
``benchmarks/bench_targets.py`` and ``tests/test_graph_proximity.py``
import from this module; the constants must not be duplicated
elsewhere.

The floor is the value below which the build fails. It is not a
target. Targets (the value we would prefer to recover toward) are
not encoded here; raise the floor when measurement supports it.

Phase-by-phase history of the floor walking down as the corpus grew
from 72 to 276 rules (preserved verbatim from the original site at
``tests/test_graph_proximity.py:32-61`` before consolidation):

    MRR5 / HitRate  When           Reason
    --------------  -------------  -------------------------------------
    0.78 / 0.90     baseline       Phase 5 baseline, 72-rule corpus.
    0.75 / 0.90     2026-05-10     Dead-workflow cleanup (deleted 17,
                                   demoted 12).
    0.72 / 0.90     2026-05-10     Phase 1A (17 SEC-INJ-*) + 1B
                                   (27 SEC-AUTH/AUTHZ/VAL-*).
    0.72 / 0.88     2026-05-10     Phase 1C (19 SEC-CRYPTO/HDR/RATE-*).
    0.70 / 0.88     2026-05-10     Phase 1D (10 SEC-DATA/DEP-*) closes
                                   Phase 1.
    0.65 / 0.84     2026-05-10     Phase 2A (33 CLEAN/DRY-*); ground
                                   truth rewritten for renamed IDs but
                                   the expanded rule space dilutes
                                   ambiguous-query MRR.
    0.55 / 0.80     2026-05-10     Phase 2B (27 SOLID/ARCH-*); ground
                                   truth rewritten for 3 more renames.
                                   Corpus now ~2.7x its original size;
                                   the original 83 queries undersample
                                   the expanded space.
    0.50 / 0.80     2026-05-10     Phase 3A (32 TEST/ERR-*); 2 more
                                   renames.
    0.50 / 0.78     2026-05-10     Phase 3B (14 PERF-* with
                                   PERF-QUERY-001 mandatory).
    0.45 / 0.78     2026-05-10     Phase 4 (30 SCALE/API/DOC-*);
                                   ARCH-TYPE-001 renamed.
    0.45 / 0.75     2026-05-10     Phase 6 ground-truth expansion:
                                   ground-truth queries grew from 83
                                   to 165 (added 82 keyword queries
                                   targeting new public-rulebook IDs).
                                   Ambiguous subset unchanged at 19;
                                   hit-rate denominator grew while new
                                   queries averaged slightly below the
                                   original set, so hit-rate floor
                                   adjusted to 0.75 with margin.

Each public-rulebook sub-phase diluted the ambiguous-set MRR / hit
rate. After full Phase 1-5 expansion (276 rules / 30 mandatory) and
Phase 6 ground-truth refresh, floors stabilized at 0.45 / 0.75
against the expanded corpus and 165-query ground truth.

Open question (2026-05-13). Re-measurement against the 276-rule
corpus on a current daemon produced MRR@5 = 0.4886 (passes 0.45) and
hit-rate = 0.7576 (passes 0.75 by 0.0076). The floor walk was not
covering for a small-corpus measurement artifact -- the 19 ambiguous
queries are stable, but ranking against them genuinely weakened as
the corpus grew. The v1.1.0 work tracks expanding the ambiguous set
toward ~70 queries (proportional to the 3.8x corpus growth) and
recovering toward the pre-expansion floor.

When raising a floor here, also append a new row to the history
table above. The history is append-only; do not delete prior rows
even when superseded.
"""

MRR5_FLOOR = 0.45
HIT_RATE_FLOOR = 0.75
