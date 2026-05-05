"""Phase 6a: Pydantic node models for methodology types.

Tests the 10 new Pydantic models defined in
docs/phase-0-schema-proposal.md:
  Retrievable: Skill, Playbook, Technique, AntiPattern,
               ForbiddenResponse
  Non-retrievable: Phase, Rationalization, PressureScenario,
                   WorkedExample, SubagentRole

Each model inherits from MethodologyNode (the shared base with the
17 common fields per the proposal's "Common base fields" table).
Each test class covers: instantiation with required fields, ID
prefix validation, ID format validation, defaults applied, JSON
round-trip.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from writ.graph.schema import (
    AntiPattern,
    Confidence,
    ForbiddenResponse,
    MethodologyNode,
    Phase,
    Playbook,
    PressureScenario,
    Rationalization,
    Severity,
    Skill,
    SubagentRole,
    Technique,
    WorkedExample,
)


# --- Shared fixture: minimal valid kwargs for the base ----------------------


def base_kwargs() -> dict:
    """Minimal required-field kwargs for any MethodologyNode subclass."""
    return {
        "domain": "process",
        "severity": Severity.MEDIUM,
        "scope": "session",
        "trigger": "when planning a non-trivial task",
        "statement": "use a written plan",
        "rationale": "verbal plans drift between sessions",
        "last_validated": date(2026, 5, 3),
    }


# --- MethodologyNode base ----------------------------------------------------


class TestMethodologyNodeBase:
    """The shared base class carries the 17 common fields and defaults."""

    def test_base_class_exists_and_is_pydantic_model(self) -> None:
        from pydantic import BaseModel
        assert issubclass(MethodologyNode, BaseModel)

    def test_base_carries_required_common_fields(self) -> None:
        fields = MethodologyNode.model_fields
        # severity is split between _RetrievableBase (required) and
        # _NonRetrievableBase (optional) by design; not on the shared base.
        for required in (
            "domain", "scope", "trigger", "statement",
            "rationale", "last_validated",
        ):
            assert required in fields, f"missing required base field: {required}"

    def test_base_carries_optional_fields_with_defaults(self) -> None:
        fields = MethodologyNode.model_fields
        for optional in (
            "tags", "confidence", "authority", "staleness_window",
            "evidence", "times_seen_positive", "times_seen_negative",
            "last_seen", "source_attribution", "source_commit", "body",
        ):
            assert optional in fields, f"missing optional base field: {optional}"


# --- Helpers for prefix / format-error testing ------------------------------


def _wrong_prefix(model_cls, id_field: str, wrong_id: str, **extra) -> None:
    """Assert that the wrong prefix is rejected."""
    with pytest.raises(ValidationError):
        model_cls(**base_kwargs(), **{id_field: wrong_id}, **extra)


def _bad_format(model_cls, id_field: str, bad_id: str, **extra) -> None:
    """Assert that a malformed ID (doesn't match RULE_ID_PATTERN) is rejected."""
    with pytest.raises(ValidationError):
        model_cls(**base_kwargs(), **{id_field: bad_id}, **extra)


def _round_trip(instance) -> None:
    """Assert model_validate_json(model_dump_json) returns equal instance."""
    cls = type(instance)
    j = instance.model_dump_json()
    rt = cls.model_validate_json(j)
    assert rt == instance


# --- Skill (SKL-) ------------------------------------------------------------


class TestSkillModel:
    def test_instantiates_with_minimum_fields(self) -> None:
        s = Skill(**base_kwargs(), skill_id="SKL-PROC-BRAIN-001")
        assert s.skill_id == "SKL-PROC-BRAIN-001"

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(Skill, "skill_id", "PBK-PROC-BRAIN-001")

    def test_rejects_malformed_id(self) -> None:
        _bad_format(Skill, "skill_id", "skl-proc-brain-001")  # lowercase

    def test_inherits_base_defaults(self) -> None:
        s = Skill(**base_kwargs(), skill_id="SKL-PROC-BRAIN-001")
        assert s.tags == []
        assert s.confidence == Confidence.PRODUCTION_VALIDATED
        assert s.body == ""

    def test_round_trip_json(self) -> None:
        s = Skill(**base_kwargs(), skill_id="SKL-PROC-BRAIN-001")
        _round_trip(s)


# --- Playbook (PBK-) ---------------------------------------------------------


class TestPlaybookModel:
    def test_instantiates_with_required_fields(self) -> None:
        pb = Playbook(
            **base_kwargs(),
            playbook_id="PBK-PROC-PLAN-001",
            phase_ids=["PHA-PLAN-001", "PHA-PLAN-002"],
        )
        assert pb.playbook_id == "PBK-PROC-PLAN-001"
        assert pb.phase_ids == ["PHA-PLAN-001", "PHA-PLAN-002"]

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            Playbook, "playbook_id", "SKL-PROC-PLAN-001",
            phase_ids=["PHA-X-001"],
        )

    def test_rejects_malformed_id(self) -> None:
        _bad_format(
            Playbook, "playbook_id", "PBK-bad-id",
            phase_ids=["PHA-X-001"],
        )

    def test_optional_fields_default_empty(self) -> None:
        pb = Playbook(
            **base_kwargs(), playbook_id="PBK-PROC-PLAN-001",
            phase_ids=["PHA-PLAN-001"],
        )
        assert pb.preconditions == []
        assert pb.dispatched_roles == []

    def test_round_trip_json(self) -> None:
        pb = Playbook(
            **base_kwargs(), playbook_id="PBK-PROC-PLAN-001",
            phase_ids=["PHA-PLAN-001", "PHA-PLAN-002"],
            preconditions=["RUL-PRE-001"],
            dispatched_roles=["ROL-CODE-REVIEWER-001"],
        )
        _round_trip(pb)


# --- Technique (TEC-) --------------------------------------------------------


class TestTechniqueModel:
    def test_instantiates(self) -> None:
        t = Technique(**base_kwargs(), technique_id="TEC-PROC-WORKTREE-001")
        assert t.technique_id == "TEC-PROC-WORKTREE-001"

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(Technique, "technique_id", "SKL-PROC-WORKTREE-001")

    def test_rejects_malformed_id(self) -> None:
        _bad_format(Technique, "technique_id", "TEC")  # too short

    def test_round_trip_json(self) -> None:
        t = Technique(**base_kwargs(), technique_id="TEC-PROC-WORKTREE-001")
        _round_trip(t)


# --- AntiPattern (ANT-) ------------------------------------------------------


class TestAntiPatternModel:
    def test_instantiates_with_required_fields(self) -> None:
        ap = AntiPattern(
            **base_kwargs(),
            antipattern_id="ANT-PROC-TDD-001",
            counter_nodes=["SKL-PROC-TDD-001"],
        )
        assert ap.antipattern_id == "ANT-PROC-TDD-001"
        assert ap.counter_nodes == ["SKL-PROC-TDD-001"]

    def test_named_in_optional(self) -> None:
        ap = AntiPattern(
            **base_kwargs(), antipattern_id="ANT-PROC-TDD-001",
            counter_nodes=["SKL-X-001"],
        )
        assert ap.named_in is None

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            AntiPattern, "antipattern_id", "SKL-PROC-TDD-001",
            counter_nodes=["SKL-X-001"],
        )

    def test_round_trip_json(self) -> None:
        ap = AntiPattern(
            **base_kwargs(), antipattern_id="ANT-PROC-TDD-001",
            counter_nodes=["SKL-PROC-TDD-001"],
            named_in="writ-methodology@1.0:testing-anti-patterns",
        )
        _round_trip(ap)


# --- ForbiddenResponse (FRB-) ------------------------------------------------


class TestForbiddenResponseModel:
    def test_instantiates_with_required_fields(self) -> None:
        fr = ForbiddenResponse(
            **base_kwargs(),
            forbidden_id="FRB-COMMS-001",
            forbidden_phrases=["You're absolutely right!"],
            what_to_say_instead="Address the technical content directly.",
        )
        assert fr.forbidden_id == "FRB-COMMS-001"

    def test_always_on_defaults_true(self) -> None:
        fr = ForbiddenResponse(
            **base_kwargs(), forbidden_id="FRB-COMMS-001",
            forbidden_phrases=["x"], what_to_say_instead="y",
        )
        assert fr.always_on is True

    def test_always_on_can_be_overridden(self) -> None:
        fr = ForbiddenResponse(
            **base_kwargs(), forbidden_id="FRB-COMMS-001",
            forbidden_phrases=["x"], what_to_say_instead="y",
            always_on=False,
        )
        assert fr.always_on is False

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            ForbiddenResponse, "forbidden_id", "SKL-COMMS-001",
            forbidden_phrases=["x"], what_to_say_instead="y",
        )

    def test_round_trip_json(self) -> None:
        fr = ForbiddenResponse(
            **base_kwargs(), forbidden_id="FRB-COMMS-001",
            forbidden_phrases=["You're absolutely right!"],
            what_to_say_instead="Address the technical content directly.",
        )
        _round_trip(fr)


# --- Phase (PHA-) ------------------------------------------------------------


class TestPhaseModel:
    def test_instantiates_with_required_fields(self) -> None:
        p = Phase(
            **base_kwargs(),
            phase_id="PHA-PLAN-001",
            position=1,
            name="Understand intent",
            description="Read user request and existing code",
            parent_playbook_id="PBK-PROC-PLAN-001",
        )
        assert p.position == 1
        assert p.parent_playbook_id == "PBK-PROC-PLAN-001"

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            Phase, "phase_id", "SKL-PLAN-001",
            position=1, name="x", description="y",
            parent_playbook_id="PBK-X-001",
        )

    def test_round_trip_json(self) -> None:
        p = Phase(
            **base_kwargs(), phase_id="PHA-PLAN-001",
            position=1, name="Understand intent",
            description="Read user request",
            parent_playbook_id="PBK-PROC-PLAN-001",
        )
        _round_trip(p)


# --- Rationalization (RAT-) --------------------------------------------------


class TestRationalizationModel:
    def test_instantiates_with_required_fields(self) -> None:
        r = Rationalization(
            **base_kwargs(),
            rationalization_id="RAT-BRAIN-001",
            thought="just one quick fix, no plan needed",
            counter="every 'quick fix' that bypasses planning is the one that breaks production",
            attached_to="SKL-PROC-PLAN-001",
        )
        assert r.thought.startswith("just one quick fix")
        assert r.attached_to == "SKL-PROC-PLAN-001"

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            Rationalization, "rationalization_id", "ANT-BRAIN-001",
            thought="x", counter="y", attached_to="SKL-X-001",
        )

    def test_round_trip_json(self) -> None:
        r = Rationalization(
            **base_kwargs(), rationalization_id="RAT-BRAIN-001",
            thought="x", counter="y", attached_to="SKL-X-001",
        )
        _round_trip(r)


# --- PressureScenario (PSC-) -------------------------------------------------


class TestPressureScenarioModel:
    def test_instantiates_with_required_fields(self) -> None:
        ps = PressureScenario(
            **base_kwargs(),
            scenario_id="PSC-VERIFY-001",
            prompt="Did the tests pass?",
            expected_compliance="model re-runs tests before answering",
            failure_patterns=["yes, all passing", "should be fine"],
            rule_under_test="ENF-VERIFY-001",
            difficulty="medium",
        )
        assert ps.difficulty == "medium"
        assert len(ps.failure_patterns) == 2

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            PressureScenario, "scenario_id", "SKL-VERIFY-001",
            prompt="x", expected_compliance="y",
            failure_patterns=["z"], rule_under_test="ENF-X-001",
            difficulty="easy",
        )

    def test_round_trip_json(self) -> None:
        ps = PressureScenario(
            **base_kwargs(), scenario_id="PSC-VERIFY-001",
            prompt="Did it pass?", expected_compliance="re-verify",
            failure_patterns=["yes"], rule_under_test="ENF-VERIFY-001",
            difficulty="hard",
        )
        _round_trip(ps)


# --- WorkedExample (EXM-) ----------------------------------------------------


class TestWorkedExampleModel:
    def test_instantiates_with_required_fields(self) -> None:
        ex = WorkedExample(
            **base_kwargs(),
            example_id="EXM-PLAN-001",
            title="Pre-plan saves a day of rework",
            before="user requested a refactor; I started typing",
            applied_skill="SKL-PROC-PLAN-001",
            result="caught two scope landmines before any code was written",
            linked_skill="SKL-PROC-PLAN-001",
        )
        assert ex.applied_skill == "SKL-PROC-PLAN-001"

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            WorkedExample, "example_id", "SKL-PLAN-001",
            title="x", before="y", applied_skill="SKL-X-001",
            result="z", linked_skill="SKL-X-001",
        )

    def test_round_trip_json(self) -> None:
        ex = WorkedExample(
            **base_kwargs(), example_id="EXM-PLAN-001",
            title="x", before="y", applied_skill="SKL-X-001",
            result="z", linked_skill="SKL-X-001",
        )
        _round_trip(ex)


# --- SubagentRole (ROL-) -----------------------------------------------------


class TestSubagentRoleModel:
    def test_instantiates_with_required_fields(self) -> None:
        sr = SubagentRole(
            **base_kwargs(),
            role_id="ROL-CODE-REVIEWER-001",
            name="writ-code-reviewer",
            prompt_template="Review this diff for ARCH-* and PHP-* rule compliance.",
        )
        assert sr.name == "writ-code-reviewer"

    def test_optional_fields_default_correctly(self) -> None:
        sr = SubagentRole(
            **base_kwargs(), role_id="ROL-CODE-REVIEWER-001",
            name="x", prompt_template="y",
        )
        assert sr.dispatched_by == []
        assert sr.model_preference is None

    def test_rejects_wrong_prefix(self) -> None:
        _wrong_prefix(
            SubagentRole, "role_id", "SKL-CODE-REVIEWER-001",
            name="x", prompt_template="y",
        )

    def test_round_trip_json(self) -> None:
        sr = SubagentRole(
            **base_kwargs(), role_id="ROL-CODE-REVIEWER-001",
            name="writ-code-reviewer",
            prompt_template="Review this diff.",
            dispatched_by=["PBK-PROC-SDD-001"],
            model_preference="haiku",
        )
        _round_trip(sr)


# --- Cross-cutting: Rule untouched -------------------------------------------


class TestRuleUnchanged:
    """Sanity: existing Rule model still imports and instantiates as before."""

    def test_rule_still_importable_and_works(self) -> None:
        from writ.graph.schema import Rule
        # Smoke-instantiate with the Rule model's full required-field set.
        # If this breaks, Phase 6a leaked into the existing Rule contract.
        r = Rule(
            rule_id="ENF-X-001", domain="test", severity=Severity.LOW,
            scope="session", trigger="t", statement="s",
            violation="v", pass_example="p", enforcement="advisory-only",
            rationale="r", last_validated=date(2026, 5, 3),
        )
        assert r.rule_id == "ENF-X-001"


# --- Cross-cutting: model count enforces the contract -----------------------


class TestModelCount:
    """Enforces 'exactly 10 new MethodologyNode subclasses' contract."""

    def test_exactly_ten_methodology_subclasses(self) -> None:
        import writ.graph.schema as schema
        # Concrete leaf classes only -- exclude underscore-prefixed
        # intermediate bases (_RetrievableBase / _NonRetrievableBase) and
        # the public MethodologyNode alias itself.
        subclasses = {
            cls for name, cls in vars(schema).items()
            if isinstance(cls, type)
            and issubclass(cls, MethodologyNode)
            and cls is not MethodologyNode
            and not cls.__name__.startswith("_")
        }
        assert len(subclasses) == 10, (
            f"Phase 6a contract requires exactly 10 concrete MethodologyNode "
            f"subclasses; found {len(subclasses)}: "
            f"{sorted(c.__name__ for c in subclasses)}"
        )
