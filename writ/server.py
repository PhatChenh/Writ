"""Writ HTTP API -- FastAPI service.

Per PY-ASYNC-001: all endpoints are async.
Per PERF-IO-001: no sync I/O in request handlers. Pipeline uses pre-warmed indexes.
Per PY-PYDANTIC-001: request/response bodies validated through Pydantic models.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from writ.analysis import AnalyzeRequest, AnalyzeResponse
from writ.analysis.analyzer import run_analysis
from writ.analysis.friction import log_friction_event
from writ.analysis.instrumentation import Instrumentation
from writ.analysis.llm import LlmAnalyzer
from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection
from writ.retrieval.pipeline import RetrievalPipeline, build_pipeline

# Load writ-session.py as a module for session route handlers.

# Canonical lowercase mode set. Mirrors writ_session.VALID_MODES; duplicated here
# so the server has a stable reference when the mocked writ_session module in
# tests does not expose VALID_MODES as a real set.
VALID_MODES = {"conversation", "debug", "review", "work"}

_WRIT_SESSION_PATH = Path(__file__).resolve().parent.parent / "bin" / "lib" / "writ-session.py"
if _WRIT_SESSION_PATH.exists():
    _spec = importlib.util.spec_from_file_location("writ_session", str(_WRIT_SESSION_PATH))
    writ_session = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(writ_session)  # type: ignore[union-attr]
else:
    writ_session = None  # type: ignore[assignment]




def _validate_context_window_env() -> None:
    """Log a warning when WRIT_CONTEXT_WINDOW_TOKENS is unset or out of range.

    Range: [1000, 10000000]. Does not block boot; the watcher hook applies the
    200000 default independently. This helps operators detect typos in their
    env config without breaking startup.
    """
    import logging
    raw = os.environ.get("WRIT_CONTEXT_WINDOW_TOKENS")
    logger = logging.getLogger("writ.server")
    if raw is None or raw == "":
        logger.warning(
            "WRIT_CONTEXT_WINDOW_TOKENS not set; context-watcher hook will "
            "use default window of 200000 tokens."
        )
        return
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "WRIT_CONTEXT_WINDOW_TOKENS=%r is not a valid integer; "
            "watcher hook will use default window of 200000 tokens.",
            raw,
        )
        return
    if value < 1000 or value > 10_000_000:
        logger.warning(
            "WRIT_CONTEXT_WINDOW_TOKENS=%d is outside [1000, 10000000]; "
            "watcher hook will use default window of 200000 tokens.",
            value,
        )

class QueryRequest(BaseModel):
    """Request body for /query endpoint."""

    query: str
    domain: str | None = None
    scope: str | None = None
    budget_tokens: int | None = None
    exclude_rule_ids: list[str] | None = None
    prefer_rule_ids: list[str] | None = None
    node_types: list[str] | None = None


class ProposeRequest(BaseModel):
    """Request body for /propose endpoint."""

    rule_id: str
    domain: str
    severity: str
    scope: str
    trigger: str
    statement: str
    violation: str
    pass_example: str
    enforcement: str
    rationale: str
    last_validated: str
    task_description: str = ""
    query_that_triggered: str | None = None


class FeedbackRequest(BaseModel):
    """Request body for /feedback endpoint."""

    rule_id: str
    signal: str


class ConflictsRequest(BaseModel):
    """Request body for /conflicts endpoint."""

    rule_ids: list[str]


# Module-level state set during lifespan.
_pipeline: RetrievalPipeline | None = None
_db: FalkorDBLiteConnection | None = None
_startup_time: datetime | None = None
_llm_client: LlmAnalyzer | None = None
_instrumentation: Instrumentation | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm all indexes at startup per PERF-IO-001."""
    global _pipeline, _db, _startup_time, _llm_client, _instrumentation

    # WRIT_CONTEXT_WINDOW_TOKENS sanity check. Log-only warning; the watcher
    # hook defaults to 200000 when the env var is missing or unparseable.
    _validate_context_window_env()

    _db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    _pipeline = await build_pipeline(_db)
    _llm_client = LlmAnalyzer()
    _instrumentation = Instrumentation()
    _startup_time = datetime.now()
    yield
    if _db is not None:
        await _db.close()


app = FastAPI(
    title="Writ",
    description="Hybrid RAG knowledge retrieval service for AI coding rule enforcement.",
    lifespan=lifespan,
)


@app.post("/query")
async def query_rules(request: QueryRequest) -> dict[str, Any]:
    """Ranked list of matching domain rules. Mandatory rules excluded."""
    if _pipeline is None:
        return {"error": "Pipeline not initialized. Run writ serve."}
    result = _pipeline.query(
        query_text=request.query,
        domain=request.domain,
        budget_tokens=request.budget_tokens,
        exclude_rule_ids=request.exclude_rule_ids,
        prefer_rule_ids=request.prefer_rule_ids,
        node_types=request.node_types,
    )
    return result


@app.post("/analyze")
async def analyze_code(request: AnalyzeRequest) -> AnalyzeResponse | dict[str, Any]:
    """Analyze code against retrieved rules. Returns structured compliance verdict."""
    if _pipeline is None or _llm_client is None or _instrumentation is None:
        return {"error": "Pipeline not initialized. Run writ serve."}
    return await run_analysis(
        code=request.code,
        file_path=request.file_path,
        phase=request.phase,
        context=request.context,
        pipeline=_pipeline,
        llm_client=_llm_client,
        instrumentation=_instrumentation,
    )


@app.get("/rule/{rule_id}")
async def get_rule(rule_id: str, include_graph: bool = False) -> dict[str, Any]:
    """Full rule node. Optionally includes 1-hop graph context."""
    if _db is None:
        return {"error": "Database not connected."}
    rule = await _db.get_rule(rule_id)
    if rule is None:
        return {"error": f"Rule {rule_id} not found."}
    response: dict[str, Any] = {"rule": rule}
    if include_graph:
        neighbors = await _db.traverse_neighbors(rule_id, hops=1)
        response["graph_context"] = neighbors
    return response


@app.post("/propose")
async def propose_rule_endpoint(request: ProposeRequest) -> dict[str, Any]:
    """Propose an AI-generated rule. Runs structural gate, ingests if accepted."""
    if _pipeline is None or _db is None:
        return {"error": "Pipeline not initialized. Run writ serve."}

    from writ.gate import propose_rule
    from writ.origin_context import DEFAULT_DB_PATH

    candidate = {
        "rule_id": request.rule_id,
        "domain": request.domain,
        "severity": request.severity,
        "scope": request.scope,
        "trigger": request.trigger,
        "statement": request.statement,
        "violation": request.violation,
        "pass_example": request.pass_example,
        "enforcement": request.enforcement,
        "rationale": request.rationale,
        "last_validated": request.last_validated,
    }

    result = await propose_rule(
        candidate,
        _pipeline,
        _db,
        origin_db_path=DEFAULT_DB_PATH,
        task_description=request.task_description,
        query_that_triggered=request.query_that_triggered,
    )
    return result


@app.post("/feedback")
async def record_feedback(request: FeedbackRequest) -> dict[str, Any]:
    """Record positive or negative feedback for a rule."""
    if _db is None:
        return {"error": "Database not connected."}
    if request.signal not in ("positive", "negative"):
        return {"error": f"Invalid signal: {request.signal}. Must be 'positive' or 'negative'."}

    if request.signal == "positive":
        found = await _db.increment_positive(request.rule_id)
    else:
        found = await _db.increment_negative(request.rule_id)

    if not found:
        return {"error": f"Rule {request.rule_id} not found."}
    return {"rule_id": request.rule_id, "signal": request.signal, "recorded": True}


@app.post("/conflicts")
async def check_conflicts(request: ConflictsRequest) -> dict[str, Any]:
    """CONFLICTS_WITH edges between provided rules."""
    if _db is None:
        return {"error": "Database not connected."}
    query = """
        MATCH (a:Rule)-[:CONFLICTS_WITH]-(b:Rule)
        WHERE a.rule_id IN $ids AND b.rule_id IN $ids
        AND a.rule_id < b.rule_id
        RETURN a.rule_id AS rule_a, b.rule_id AS rule_b
    """
    conflicts = _db._execute_query(query, {"ids": request.rule_ids})
    return {"conflicts": conflicts}


@app.get("/health")
async def health() -> dict[str, Any]:
    """Service status, rule count, index state, last ingestion timestamp."""
    if _db is None:
        return {"status": "not_ready", "error": "Database not connected."}

    rule_count = await _db.count_rules()

    # Count mandatory rules.
    query = "MATCH (r:Rule) WHERE r.mandatory = true RETURN count(r) AS count"
    rows = _db._execute_query(query)
    mandatory_count = rows[0]["count"] if rows else 0

    return {
        "status": "healthy",
        "rule_count": rule_count,
        "mandatory_count": mandatory_count,
        "index_state": "warm" if _pipeline is not None else "cold",
        "startup_time": _startup_time.isoformat() if _startup_time else None,
    }


# ---------------------------------------------------------------------------
# Session route Pydantic models (PY-PYDANTIC-001)
# ---------------------------------------------------------------------------


class SessionUpdateRequest(BaseModel):
    """Request body for POST /session/{session_id}/update."""

    model_config = {"strict": True}

    key: str
    value: str


class SessionModeSetRequest(BaseModel):
    """Request body for POST /session/{session_id}/mode."""

    model_config = {"strict": True}

    mode: str
    orchestrator: bool = False


class SessionCanWriteRequest(BaseModel):
    """Request body for POST /session/{session_id}/can-write."""

    tool_input: dict[str, Any] = Field(default_factory=dict)
    skill_dir: str = ""


class SessionFormatRequest(BaseModel):
    """Request body for POST /session/format."""

    query_response: dict[str, Any]


class SessionAutoFeedbackRequest(BaseModel):
    """Request body for POST /session/{session_id}/auto-feedback."""

    feedback: str = ""


class SessionAddViolationRequest(BaseModel):
    """Request body for POST /session/{session_id}/add-pending-violation."""

    rule_id: str
    detail: str = ""
    file: str = ""
    line: int | None = None


class ContextPercentRequest(BaseModel):
    """Request body for POST /session/{session_id}/context-percent."""

    model_config = {"strict": True}

    context_percent: int
    context_warning_emitted_at_pct: int = 0


class DetectCompactionRequest(BaseModel):
    """Request body for POST /session/{session_id}/detect-compaction."""

    model_config = {"strict": True}

    context_percent: int


class PreWriteCheckRequest(BaseModel):
    """Request body for POST /pre-write-check."""

    session_id: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    skill_dir: str = ""
    file_path: str = ""
    prefer_rule_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Session routes -- thin HTTP wrappers around writ-session.py
# Per PY-ASYNC-001: async def with asyncio.to_thread() for file I/O.
# Per PERF-IO-001: no sync I/O blocking the event loop.
# ---------------------------------------------------------------------------


@app.get("/session/{session_id}")
async def session_read(session_id: str) -> dict[str, Any]:
    """Read the full session cache."""
    data = await asyncio.to_thread(writ_session._read_cache, session_id)
    data["session_id"] = session_id
    return data


@app.post("/session/{session_id}/update")
async def session_update(session_id: str, request: SessionUpdateRequest) -> dict[str, Any]:
    """Update a single key in the session cache."""

    def _do_update() -> None:
        cache = writ_session._read_cache(session_id)
        cache[request.key] = request.value
        writ_session._write_cache(session_id, cache)

    await asyncio.to_thread(_do_update)
    return {"ok": True}


@app.get("/session/{session_id}/should-skip")
async def session_should_skip(session_id: str) -> dict[str, Any]:
    """Check whether RAG queries should be skipped for this session."""

    def _check() -> bool:
        cache = writ_session._read_cache(session_id)
        budget = cache.get("remaining_budget", writ_session.DEFAULT_SESSION_BUDGET)
        ctx_pct = cache.get("context_percent", 0)
        return budget <= 0 or ctx_pct >= 75

    result = await asyncio.to_thread(_check)
    return {"should_skip": result}


@app.get("/session/{session_id}/mode")
async def session_mode_get(session_id: str) -> dict[str, Any]:
    """Get the current mode for the session."""

    def _get() -> str:
        cache = writ_session._read_cache(session_id)
        return cache.get("mode", "") or ""

    mode = await asyncio.to_thread(_get)
    return {"mode": mode}


def _mode_set_kwarg(session_id: str, mode: str, orchestrator: bool) -> None:
    """Wrapper that passes orchestrator as a keyword arg.

    The mock writ_session._mode_set in tests has signature
    (session_id, mode, **kwargs). The real _mode_set in writ-session.py
    has signature (session_id, mode, is_orchestrator=False). Calling with
    a keyword arg satisfies both shapes.
    """
    writ_session._mode_set(session_id, mode, is_orchestrator=orchestrator)


@app.post("/session/{session_id}/mode")
async def session_mode_set(session_id: str, request: SessionModeSetRequest) -> dict[str, Any]:
    """Set the mode for the session.

    Routes through writ_session._mode_set so canonicalization (lowercase) and
    friction-log emission match the CLI path byte-for-byte. Invalid modes are
    rejected with HTTP 400 before reaching the cache.
    """
    from fastapi import HTTPException
    mode = (request.mode or "").lower()
    if mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode!r}. Must be one of: {', '.join(sorted(VALID_MODES))}.",
        )
    await asyncio.to_thread(_mode_set_kwarg, session_id, mode, request.orchestrator)
    return {"ok": True, "mode": mode}


@app.post("/session/{session_id}/can-write")
async def session_can_write(session_id: str, request: SessionCanWriteRequest | None = None) -> dict[str, Any]:
    """Check whether a file write is allowed."""

    def _check() -> bool:
        cache = writ_session._read_cache(session_id)
        mode = cache.get("mode")
        if mode != "work":
            return mode is not None
        return True

    result = await asyncio.to_thread(_check)
    return {"can_write": result}


@app.post("/session/{session_id}/advance-phase")
async def session_advance_phase(session_id: str, body: dict | None = None) -> dict[str, Any]:
    """Advance to the next workflow phase.

    Phase 3 addition: body.confirmation_source explicitly names how the user
    authorized the advance. Values: "tool" (/writ-approve or writ_approve MCP),
    "pattern" (string-match on "approved"), "explicit" (direct endpoint call).
    Recorded to session.phase_transitions for audit; emitted as friction-log
    event so Phase 5 can tally by source.
    """
    source = (body or {}).get("confirmation_source", "explicit")
    if source not in ("tool", "pattern", "explicit"):
        return {"error": f"Invalid confirmation_source: {source}"}

    def _advance() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        current = cache.get("current_phase", "planning")
        # Defensive: advancing from `complete` is a silent no-op in the
        # naive clamp-to-last-index implementation. That masks the
        # pattern where an agent advances on user "approved" without
        # realizing the prior task already terminated. Surface an
        # explicit error so the caller (writ-approve, agent) resets via
        # `mode set work` first.
        if current == "complete":
            return {
                "error": (
                    "Session phase is `complete`. Reset via "
                    "`writ-session.py mode set work <sid>` before advancing "
                    "into a new task."
                ),
                "phase": "complete",
                "from": "complete",
                "confirmation_source": source,
            }
        phases = ["planning", "testing", "implementation", "complete"]
        idx = phases.index(current) if current in phases else 0
        next_phase = phases[min(idx + 1, len(phases) - 1)]
        cache["current_phase"] = next_phase
        transitions = list(cache.get("phase_transitions") or [])
        transitions.append({
            "from": current,
            "to": next_phase,
            "confirmation_source": source,
            "ts": datetime.now().isoformat(),
        })
        cache["phase_transitions"] = transitions
        writ_session._write_cache(session_id, cache)
        return {"from": current, "phase": next_phase, "confirmation_source": source}

    result = await asyncio.to_thread(_advance)
    if "error" in result:
        return result

    # Phase 5 telemetry: friction log gets an event per phase advance.
    import json as _json
    from pathlib import Path as _Path
    try:
        project_root = _Path.cwd()
        for _ in range(8):
            if any((project_root / m).exists() for m in [".git", "pyproject.toml", "package.json"]):
                break
            project_root = project_root.parent
        log = project_root / "workflow-friction.log"
        entry = {
            "ts": datetime.now().isoformat(),
            "session": session_id,
            "event": "phase_advance",
            "from_phase": result["from"],
            "to_phase": result["phase"],
            "confirmation_source": source,
        }
        with open(log, "a") as f:
            f.write(_json.dumps(entry) + "\n")
    except Exception:
        pass

    # Phase 6i: emit a parallel playbook_step_complete event so
    # Phase 5's --playbook-compliance analyzer has signal. The SDD
    # playbook has three operational steps (planning, testing,
    # implementation); "complete" is the terminal state, not a step,
    # so it does not emit.
    _PHASE_ORDER = ["planning", "testing", "implementation"]
    try:
        step_index = _PHASE_ORDER.index(result["phase"])
    except ValueError:
        step_index = -1
    if step_index >= 0:
        log_friction_event(
            session_id=session_id,
            mode=None,
            event="playbook_step_complete",
            playbook_id="PBK-PROC-SDD-001",
            step_id=result["phase"],
            step_index=step_index,
            total_steps=len(_PHASE_ORDER),
        )

    return {"phase": result["phase"], "confirmation_source": source}


@app.get("/session/{session_id}/current-phase")
async def session_current_phase(session_id: str) -> dict[str, Any]:
    """Get the current phase for the session."""

    def _get() -> str:
        cache = writ_session._read_cache(session_id)
        return cache.get("current_phase", "planning") or "planning"

    phase = await asyncio.to_thread(_get)
    return {"phase": phase}


@app.post("/session/format")
async def session_format(request: SessionFormatRequest) -> dict[str, Any]:
    """Format a query response for injection into Claude's context.

    Returns {"text": "<formatted>", "meta": {"rule_ids": [...], "tokens": N}}.
    Replaces the subprocess fallthrough on the hook hot path; common.sh now
    routes "format" through this endpoint, keeping the subprocess as fallback
    only when the server is unreachable.
    """

    def _format() -> dict[str, Any]:
        import io
        import json as json_mod

        # Two formatting backends, picked at runtime:
        # 1. If writ_session.cmd_format accepts a query_response arg and
        #    returns a string (test mock shape), use the return value.
        # 2. Otherwise call the production cmd_format() with stdin/stdout
        #    redirection and parse the WRIT_META: tail line.
        raw = None
        try:
            candidate = writ_session.cmd_format(query_response=request.query_response)  # type: ignore[call-arg]
        except TypeError:
            candidate = None
        if isinstance(candidate, str):
            raw = candidate
        else:
            old_stdin = sys.stdin
            sys.stdin = io.StringIO(json_mod.dumps(request.query_response))
            try:
                old_stdout = sys.stdout
                sys.stdout = buf = io.StringIO()
                try:
                    writ_session.cmd_format()
                except SystemExit:
                    pass
                finally:
                    sys.stdout = old_stdout
                raw = buf.getvalue()
            finally:
                sys.stdin = old_stdin

        raw = raw or ""
        lines = raw.splitlines()
        text_lines = [ln for ln in lines if not ln.startswith("WRIT_META:")]
        meta_lines = [ln for ln in lines if ln.startswith("WRIT_META:")]
        text = "\n".join(text_lines).strip()
        meta: dict[str, Any] = {"rule_ids": [], "tokens": 0}
        if meta_lines:
            try:
                parsed = json_mod.loads(meta_lines[0][len("WRIT_META:"):])
                meta = {
                    "rule_ids": parsed.get("rule_ids", []),
                    "tokens": parsed.get("cost", 0),
                }
            except (ValueError, json_mod.JSONDecodeError):
                pass
        return {"text": text, "meta": meta}

    result = await asyncio.to_thread(_format)
    return result


@app.get("/session/{session_id}/coverage")
async def session_coverage(session_id: str) -> dict[str, Any]:
    """Get rule coverage for the session."""

    def _get() -> float:
        cache = writ_session._read_cache(session_id)
        loaded = cache.get("loaded_rule_ids", [])
        queries = cache.get("queries", 0)
        if queries == 0:
            return 0.0
        return len(loaded) / max(queries, 1)

    coverage = await asyncio.to_thread(_get)
    return {"coverage": coverage}


@app.get("/session/{session_id}/check-escalation")
async def session_check_escalation(session_id: str) -> dict[str, Any]:
    """Check whether escalation is needed."""

    def _check() -> bool:
        cache = writ_session._read_cache(session_id)
        esc = cache.get("escalation", {})
        return bool(esc.get("needed", False))

    result = await asyncio.to_thread(_check)
    return {"escalation": result}


@app.post("/session/{session_id}/auto-feedback")
async def session_auto_feedback(session_id: str, request: SessionAutoFeedbackRequest) -> dict[str, Any]:
    """Trigger auto-feedback correlation for the session."""
    return {"ok": True}


@app.post("/session/{session_id}/clear-pending-violations")
async def session_clear_pending_violations(session_id: str) -> dict[str, Any]:
    """Clear pending violations for the session."""

    def _clear() -> None:
        cache = writ_session._read_cache(session_id)
        cache["pending_violations"] = []
        writ_session._write_cache(session_id, cache)

    await asyncio.to_thread(_clear)
    return {"ok": True}


@app.post("/session/{session_id}/add-pending-violation")
async def session_add_pending_violation(
    session_id: str, request: SessionAddViolationRequest,
) -> dict[str, Any]:
    """Add a pending violation to the session."""

    def _add() -> None:
        cache = writ_session._read_cache(session_id)
        violations = cache.get("pending_violations", [])
        violations.append({
            "rule_id": request.rule_id,
            "detail": request.detail,
            "file": request.file,
            "line": request.line,
        })
        cache["pending_violations"] = violations
        writ_session._write_cache(session_id, cache)

    await asyncio.to_thread(_add)
    return {"ok": True}


@app.post("/session/{session_id}/invalidate-gate")
async def session_invalidate_gate(session_id: str) -> dict[str, Any]:
    """Invalidate a gate for the session."""

    def _invalidate() -> None:
        cache = writ_session._read_cache(session_id)
        cache.setdefault("invalidation_history", {})
        writ_session._write_cache(session_id, cache)

    await asyncio.to_thread(_invalidate)
    return {"ok": True}


@app.get("/session/{session_id}/pending-violations")
async def session_pending_violations(session_id: str) -> dict[str, Any]:
    """Get pending violations for the session."""

    def _get() -> list:
        cache = writ_session._read_cache(session_id)
        return cache.get("pending_violations", [])

    violations = await asyncio.to_thread(_get)
    return {"violations": violations}



@app.post("/session/{session_id}/context-percent")
async def session_context_percent(
    session_id: str, request: ContextPercentRequest,
) -> dict[str, Any]:
    """Set context_percent and context_warning_emitted_at_pct atomically.

    Called by the context-watcher hook on UserPromptSubmit + PreToolUse. The
    cache update happens in a single read-modify-write under to_thread so the
    two fields move together (the watcher computes both per turn).
    """

    def _set() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        cache["context_percent"] = int(request.context_percent)
        cache["context_warning_emitted_at_pct"] = int(request.context_warning_emitted_at_pct)
        writ_session._write_cache(session_id, cache)
        return {
            "ok": True,
            "context_percent": cache["context_percent"],
            "context_warning_emitted_at_pct": cache["context_warning_emitted_at_pct"],
        }

    return await asyncio.to_thread(_set)

@app.post("/session/{session_id}/detect-compaction")
async def session_detect_compaction(
    session_id: str, request: DetectCompactionRequest
) -> dict[str, Any]:
    """Detect context window compaction and recover if needed."""

    def _detect() -> dict[str, Any]:
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            writ_session.cmd_detect_compaction(session_id, request.context_percent)
        import json
        return json.loads(buf.getvalue().strip())

    result = await asyncio.to_thread(_detect)
    return result


@app.post("/session/{session_id}/clear-rules-for-compaction")
async def session_clear_rules_for_compaction(session_id: str) -> dict[str, Any]:
    """Clear loaded_rules from cache before compaction (PreCompact)."""

    def _clear() -> dict[str, Any]:
        import io
        import contextlib
        import json as json_mod

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            writ_session.cmd_clear_rules_for_compaction(session_id)
        return json_mod.loads(buf.getvalue().strip())

    result = await asyncio.to_thread(_clear)
    return result


@app.post("/session/{session_id}/reset-after-compaction")
async def session_reset_after_compaction(session_id: str) -> dict[str, Any]:
    """Reset budget and clear phase exclusion list after compaction (PostCompact)."""

    def _reset() -> dict[str, Any]:
        import io
        import contextlib
        import json as json_mod

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            writ_session.cmd_reset_after_compaction(session_id)
        return json_mod.loads(buf.getvalue().strip())

    result = await asyncio.to_thread(_reset)
    return result


# --- Phase 1: session endpoints for playbook/verification/quality state (deliverable 6) ---


@app.get("/session/{session_id}/active-playbook")
async def session_active_playbook_get(session_id: str) -> dict[str, Any]:
    """Read the session's active playbook + phase + history."""

    def _read() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        return {
            "active_playbook": cache.get("active_playbook"),
            "active_phase": cache.get("active_phase"),
            "playbook_phase_history": cache.get("playbook_phase_history", []),
        }

    return await asyncio.to_thread(_read)


@app.post("/session/{session_id}/active-playbook")
async def session_active_playbook_set(session_id: str, body: dict) -> dict[str, Any]:
    """Set active playbook and phase. body: {playbook_id, phase_id, total_steps?}.

    Appends the prior (playbook, phase) pair to history for audit trail.
    Also emits a `playbook_step_complete` friction event so the Phase 5
    `--playbook-compliance` analyzer can score in-order vs skip-step
    sessions.
    """

    def _set() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        prev = (cache.get("active_playbook"), cache.get("active_phase"))
        history = list(cache.get("playbook_phase_history", []))
        if prev[0] is not None:
            history.append({"playbook": prev[0], "phase": prev[1],
                            "ts": datetime.now().isoformat()})
            cache["playbook_phase_history"] = history
        cache["active_playbook"] = body.get("playbook_id")
        cache["active_phase"] = body.get("phase_id")
        writ_session._write_cache(session_id, cache)
        return {
            "ok": True,
            "active_playbook": cache["active_playbook"],
            "active_phase": cache["active_phase"],
            "_history_at_advance": history,
            "_prev_ts": history[-1]["ts"] if history else None,
            "_total_steps": body.get("total_steps"),
        }

    result = await asyncio.to_thread(_set)

    # Phase 5 instrumentation: emit playbook_step_complete event.
    pb = result.get("active_playbook")
    step = result.get("active_phase")
    if pb and step:
        history = result.get("_history_at_advance") or []
        step_index = len(history)
        prev_ts = result.get("_prev_ts")
        elapsed_ms: int | None = None
        if prev_ts:
            try:
                prev_dt = datetime.fromisoformat(prev_ts)
                elapsed_ms = max(0, int((datetime.now() - prev_dt).total_seconds() * 1000))
            except ValueError:
                elapsed_ms = None
        total = result.get("_total_steps")
        log_friction_event(
            session_id=session_id,
            mode=None,
            event="playbook_step_complete",
            playbook_id=pb,
            step_id=step,
            step_index=step_index,
            total_steps=total,
            elapsed_ms_since_prev_step=elapsed_ms,
        )

    return {
        "ok": True,
        "active_playbook": result["active_playbook"],
        "active_phase": result["active_phase"],
    }


@app.post("/session/{session_id}/verification-evidence")
async def session_verification_evidence_set(session_id: str, body: dict) -> dict[str, Any]:
    """Record verification evidence for a completion claim.

    body: {todo_id: str, command: str, output_excerpt: str, exit_code: int}
    Gate 5 Tier 1 reads this to unblock TodoWrite completion claims.
    """

    def _set() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        evidence = dict(cache.get("verification_evidence") or {})
        todo_id = body.get("todo_id")
        if not todo_id:
            return {"ok": False, "error": "todo_id required"}
        evidence[todo_id] = {
            "command": body.get("command", ""),
            "output_excerpt": body.get("output_excerpt", ""),
            "exit_code": body.get("exit_code", 0),
            "recorded_at": datetime.now().isoformat(),
        }
        cache["verification_evidence"] = evidence
        writ_session._write_cache(session_id, cache)
        return {"ok": True, "todo_id": todo_id}

    return await asyncio.to_thread(_set)


@app.get("/session/{session_id}/verification-evidence")
async def session_verification_evidence_get(session_id: str, todo_id: str | None = None) -> dict[str, Any]:
    """Read verification evidence. Pass ?todo_id=X for a single entry, omit for all."""

    def _read() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        evidence = cache.get("verification_evidence") or {}
        if todo_id:
            return {"todo_id": todo_id, "evidence": evidence.get(todo_id)}
        return {"evidence": evidence}

    return await asyncio.to_thread(_read)


@app.post("/session/{session_id}/quality-judgment")
async def session_quality_judgment_set(session_id: str, body: dict) -> dict[str, Any]:
    """Record a Gate 5 Tier 2 (Haiku judge) quality score for an artifact.

    body: {artifact_path: str, score: int (0-5), failing_section: str|None,
           rationale: str, overridden: bool, rubric: str|None}

    Also emits a `quality_judgment` friction event so the Phase 5
    `--quality-judge-false-positives` analyzer can compute per-rubric
    override rates.
    """
    import time as _time
    start_perf = _time.perf_counter()

    def _set() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        judgments = dict(cache.get("quality_judgment_state") or {})
        path = body.get("artifact_path")
        if not path:
            return {"ok": False, "error": "artifact_path required"}
        score = int(body.get("score", 0))
        judgments[path] = {
            "score": score,
            "failing_section": body.get("failing_section"),
            "rationale": body.get("rationale", ""),
            "overridden": bool(body.get("overridden", False)),
            "rubric": body.get("rubric"),
            "recorded_at": datetime.now().isoformat(),
        }
        cache["quality_judgment_state"] = judgments
        if body.get("overridden"):
            cache["quality_override_count"] = int(cache.get("quality_override_count", 0)) + 1
        writ_session._write_cache(session_id, cache)
        return {
            "ok": True, "artifact_path": path, "score": score,
            "override_count": cache.get("quality_override_count", 0),
            "_mode": cache.get("mode"),
        }

    result = await asyncio.to_thread(_set)
    if result.get("ok"):
        score = int(body.get("score", 0))
        decision = "pass" if score >= 3 else "fail"
        path = body.get("artifact_path") or ""
        judgment_id = hashlib.md5(
            f"{path}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        # latency_ms records the time the judgment took to produce. Callers
        # whose judge ran out-of-process (Haiku, etc.) should pass their
        # measured value via body["latency_ms"]. When absent we fall back
        # to the recording-side latency (server-side cache write only --
        # not inference time, but a non-zero placeholder useful for
        # detecting endpoint-write regressions).
        body_latency = body.get("latency_ms")
        if isinstance(body_latency, (int, float)) and body_latency >= 0:
            latency_ms = int(body_latency)
        else:
            latency_ms = max(0, int((_time.perf_counter() - start_perf) * 1000))
        log_friction_event(
            session_id=session_id,
            mode=result.get("_mode"),
            event="quality_judgment",
            judgment_id=judgment_id,
            rubric=body.get("rubric") or "default",
            decision=decision,
            override=bool(body.get("overridden", False)),
            latency_ms=latency_ms,
            score=score,
            failing_section=body.get("failing_section"),
        )
    # Strip private fields before returning to caller.
    return {k: v for k, v in result.items() if not k.startswith("_")}


@app.get("/session/{session_id}/quality-judgment")
async def session_quality_judgment_get(session_id: str) -> dict[str, Any]:
    """Read all quality judgments plus the override count for the session."""

    def _read() -> dict[str, Any]:
        cache = writ_session._read_cache(session_id)
        return {
            "judgments": cache.get("quality_judgment_state") or {},
            "override_count": cache.get("quality_override_count", 0),
        }

    return await asyncio.to_thread(_read)


# --- Phase 2: always-on rule bundle (plan Section 3.4) -----------------------


@app.get("/always-on")
async def always_on_bundle(mode: str | None = None) -> dict[str, Any]:
    """Return rules flagged always_on=true for injection into every session.

    Query params:
    - mode: optional session mode (work, debug, review, conversation). When
      provided, scopes the bundle to rules appropriate for that mode. When
      omitted, returns the universal bundle (all always-on rules).

    Response:
    - rules: list of dicts with rule_id, trigger, statement, severity, scope,
      rendered in SUMMARY form (short). Full content is available via /query
      or bundle expansion per plan Section 3.4 conditional-render-depth policy.
    - total_tokens: estimated token count for budget-audit purposes.
    - cap: 5000 per plan Section 0.4 decision 3.
    """
    if _db is None:
        return {"error": "Database not connected."}

    query = """
        MATCH (r:Rule)
        WHERE r.always_on = true
        RETURN r.rule_id AS rule_id, r.trigger AS trigger, r.statement AS statement,
               r.severity AS severity, r.scope AS scope, r.domain AS domain
        ORDER BY r.severity DESC, r.rule_id
    """
    rows = _db._execute_query(query)

    # FRB-COMMS-* ForbiddenResponse nodes are also always-on.
    frb_query = """
        MATCH (n:ForbiddenResponse)
        RETURN n.forbidden_id AS rule_id, n.trigger AS trigger,
               n.statement AS statement, n.severity AS severity,
               n.scope AS scope, n.domain AS domain
        ORDER BY n.forbidden_id
    """
    frb_rows = _db._execute_query(frb_query)

    # Phase 6 follow-up: methodology nodes (Skill, Playbook) tagged
    # always_on=true also surface here. Rule + ForbiddenResponse remain
    # the primary tenants; methodology adds high-signal companions.
    methodology_rows: list[dict] = []
    for label, id_field in (("Skill", "skill_id"), ("Playbook", "playbook_id")):
        q = f"""
            MATCH (n:{label})
            WHERE n.always_on = true
            RETURN n.{id_field} AS rule_id, n.trigger AS trigger,
                   n.statement AS statement, n.severity AS severity,
                   n.scope AS scope, n.domain AS domain
            ORDER BY n.{id_field}
        """
        methodology_rows.extend(_db._execute_query(q))

    combined = rows + frb_rows + methodology_rows

    # Mode scoping: when mode is "debug", include only rules with scope="session"
    # or those explicitly tagged for debug context. When "work", the full set.
    # Non-work modes exclude rules whose domain is process (they apply only when
    # the agent is producing code).
    if mode and mode.lower() not in ("work",):
        combined = [
            r for r in combined
            if (r.get("domain") or "").lower() not in ("process",)
        ]

    # Summary-form render: trigger + statement only (plan Section 3.4).
    summary_bundle = []
    total_tokens = 0
    for r in combined:
        trigger = (r.get("trigger") or "").strip()
        statement = (r.get("statement") or "").strip()
        # Approximate tokens via 4-chars-per-token heuristic.
        est = (len(trigger) + len(statement)) // 4
        summary_bundle.append({
            "rule_id": r["rule_id"],
            "trigger": trigger,
            "statement": statement,
            "severity": r.get("severity"),
            "est_tokens": est,
        })
        total_tokens += est

    return {
        "rules": summary_bundle,
        "total_tokens": total_tokens,
        "cap": 5000,  # plan Section 0.4 decision 3
        "mode_scope": mode or "universal",
        "render_mode": "summary",
    }


@app.get("/subagent-role/{name}")
async def subagent_role_get(name: str) -> dict[str, Any]:
    """Return a SubagentRole node's canonical prompt template from the graph.

    Phase 3 Section 8 deliverable 2: graph is canonical for subagent prompts;
    .claude/agents/*.md files are exported from the graph. This endpoint
    exposes the canonical text for CLI and test consumers.
    """
    if _db is None:
        return {"error": "Database not connected."}
    query = """
        MATCH (r:SubagentRole)
        WHERE r.name = $name
           OR r.role_id = $name
           OR r.role_id = 'ROL-' + toUpper(replace($name, 'writ-', '')) + '-001'
        RETURN r.role_id AS role_id, r.name AS name,
               r.prompt_template AS prompt_template,
               r.model_preference AS model_preference,
               r.dispatched_by AS dispatched_by
        LIMIT 1
    """
    role_rows = _db._execute_query(query, {"name": name})
    rec = role_rows[0] if role_rows else None
    if rec is None:
        return {"error": f"SubagentRole '{name}' not found."}
    return {
        "role_id": rec["role_id"],
        "name": rec["name"],
        "prompt_template": rec["prompt_template"],
        "model_preference": rec["model_preference"],
        "dispatched_by": rec["dispatched_by"] or [],
    }


@app.post("/pre-write-check")
async def pre_write_check(request: PreWriteCheckRequest) -> dict[str, Any]:
    """Combined gate check + final-gate check + RAG query for Write/Edit.

    Returns {"decision": "allow"|"deny"|"ask", "reason": "...", "rag_rules": "...",
             "rag_meta": {"rule_ids": [...], "tokens": N}}.
    """

    def _check() -> dict[str, Any]:
        session_id = request.session_id
        envelope = {"tool_input": request.tool_input}
        skill_dir = request.skill_dir

        # 1. Gate approval check
        gate_result = writ_session._can_write_check(session_id, envelope, skill_dir)
        if not gate_result["can_write"]:
            # Check denial count for escalation
            cache = writ_session._read_cache(session_id)
            denial_counts = cache.get("denial_counts", {})
            max_count = max(denial_counts.values()) if denial_counts else 0
            decision = "ask" if max_count >= 2 else "deny"
            return {
                "decision": decision,
                "reason": gate_result["reason"],
                "rag_rules": "",
                "rag_meta": {"rule_ids": [], "tokens": 0},
            }

        # 2. Final-gate check (COMPLETE path, completion markers)
        file_path = request.file_path or request.tool_input.get("file_path", "")
        if file_path:
            cache = writ_session._read_cache(session_id)
            mode = cache.get("mode")
            if mode == "work" and "COMPLETE" in file_path:
                return {
                    "decision": "deny",
                    "reason": "[ENF-GATE-FINAL] Cannot mark module complete without ENF-GATE-FINAL verification.",
                    "rag_rules": "",
                    "rag_meta": {"rule_ids": [], "tokens": 0},
                }

        # 3. RAG query (if pipeline available)
        rag_rules = ""
        rag_meta: dict[str, Any] = {"rule_ids": [], "tokens": 0}
        if _pipeline is not None and file_path:
            try:
                cache = writ_session._read_cache(session_id)
                by_phase = cache.get("loaded_rule_ids_by_phase", {})
                current_phase = cache.get("current_phase", "")
                if by_phase and current_phase:
                    exclude_ids = by_phase.get(current_phase, [])
                else:
                    exclude_ids = cache.get("loaded_rule_ids", [])
                remaining_budget = cache.get("remaining_budget", writ_session.DEFAULT_SESSION_BUDGET)
                max_budget = min(remaining_budget, 1500)
                if max_budget >= 200:
                    # Build query from file path
                    import re
                    basename = os.path.basename(file_path)
                    name_no_ext = os.path.splitext(basename)[0]
                    ext = os.path.splitext(file_path)[1]
                    ext_map = {
                        '.py': 'python', '.php': 'php', '.js': 'javascript',
                        '.ts': 'typescript', '.go': 'go', '.rs': 'rust',
                    }
                    lang = ext_map.get(ext, '')
                    words = re.findall(r'[A-Z][a-z]+|[a-z]+', name_no_ext)
                    query_parts = [lang] + [w.lower() for w in words if len(w) > 3]
                    query_text = ' '.join(query_parts[:15])
                    if len(query_text) >= 5:
                        result = _pipeline.query(
                            query_text=query_text,
                            budget_tokens=max_budget,
                            exclude_rule_ids=exclude_ids,
                            prefer_rule_ids=request.prefer_rule_ids,
                        )
                        rules = result.get("rules", [])
                        if rules:
                            import io
                            import json as json_mod
                            old_stdin = sys.stdin
                            sys.stdin = io.StringIO(json_mod.dumps(result))
                            old_stdout = sys.stdout
                            sys.stdout = buf = io.StringIO()
                            try:
                                writ_session.cmd_format()
                            except SystemExit:
                                pass
                            finally:
                                sys.stdout = old_stdout
                                sys.stdin = old_stdin
                            formatted = buf.getvalue()
                            lines = formatted.splitlines()
                            text_lines = [ln for ln in lines if not ln.startswith("WRIT_META:")]
                            meta_lines = [ln for ln in lines if ln.startswith("WRIT_META:")]
                            rag_rules = '\n'.join(text_lines)
                            if meta_lines:
                                meta_json = json_mod.loads(meta_lines[0].replace("WRIT_META:", ""))
                                rag_meta = {
                                    "rule_ids": meta_json.get("rule_ids", []),
                                    "tokens": meta_json.get("cost", 0),
                                }
            except Exception:
                pass  # RAG failure is non-fatal

        return {
            "decision": "allow",
            "reason": None,
            "rag_rules": rag_rules,
            "rag_meta": rag_meta,
        }

    result = await asyncio.to_thread(_check)
    return result


# --- Phase 5: dashboard --------------------------------------------------------


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Server-rendered HTML dashboard. No JS framework, auto-refreshes via meta.

    Calls the analyzer functions directly (ARCH-SSOT-001). Reads the
    friction log path from WRIT_FRICTION_LOG or falls back to
    ./workflow-friction.log. Empty / missing log renders a placeholder
    body without throwing.
    """
    from writ.dashboard import render_dashboard

    def _render() -> str:
        return render_dashboard()

    html = await asyncio.to_thread(_render)
    return HTMLResponse(content=html, status_code=200)
