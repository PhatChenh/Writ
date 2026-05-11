"""Tests for hooks/hooks.json event routing (Phase B + C).

Verifies the hooks manifest exists, covers all 31 registrations from
templates/settings.json, uses ${CLAUDE_PLUGIN_ROOT} for all paths, and
that every referenced script file exists on disk and is executable.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from tests.plugin.conftest import REPO_ROOT, _expand_plugin_root

HOOKS_JSON_PATH = REPO_ROOT / "hooks" / "hooks.json"

# Expected script names per event from the plan's Phase B Files section
EXPECTED_EVENT_SCRIPTS: dict[str, list[str]] = {
    "UserPromptSubmit": ["auto-approve-gate.sh", "writ-rag-inject.sh"],
    "SubagentStart": ["writ-subagent-start.sh"],
    "SubagentStop": ["writ-subagent-stop.sh"],
    "Stop": [
        "writ-context-tracker.sh",
        "friction-logger.sh",
        "enforce-violations.sh",
        "writ-verify-before-claim.sh",
    ],
    "PreCompact": ["writ-precompact.sh"],
    "PostCompact": ["writ-postcompact.sh"],
    "SessionEnd": ["writ-session-end.sh", "writ-pressure-audit.sh"],
    "CwdChanged": ["writ-cwd-changed.sh"],
    "InstructionsLoaded": ["writ-instructions-loaded.sh"],
}


def _collect_all_registrations(hooks_data: dict) -> list[dict]:
    """Flatten all hook registration entries from the hooks dict."""
    registrations = []
    hooks_section = hooks_data.get("hooks", hooks_data)
    for event_entries in hooks_section.values():
        if isinstance(event_entries, list):
            registrations.extend(event_entries)
    return registrations


def _collect_all_commands(hooks_data: dict) -> list[str]:
    """Extract all command strings from every registration entry.

    The standard Claude Code hooks schema nests commands under each matcher
    entry's ``hooks`` array: ``{matcher, hooks: [{type, command}]}``. This
    helper flattens that structure into a list of command strings.
    """
    commands = []
    hooks_section = hooks_data.get("hooks", hooks_data)
    for event_entries in hooks_section.values():
        if isinstance(event_entries, list):
            for entry in event_entries:
                if isinstance(entry, dict):
                    if "command" in entry:
                        commands.append(entry["command"])
                    inner_hooks = entry.get("hooks")
                    if isinstance(inner_hooks, list):
                        for inner in inner_hooks:
                            if isinstance(inner, dict) and "command" in inner:
                                commands.append(inner["command"])
                elif isinstance(entry, str):
                    commands.append(entry)
    return commands


def _collect_event_commands(event_entries: list) -> list[str]:
    """Extract all command strings registered under a single event."""
    commands: list[str] = []
    for entry in event_entries:
        if isinstance(entry, dict):
            if "command" in entry:
                commands.append(entry["command"])
            inner_hooks = entry.get("hooks")
            if isinstance(inner_hooks, list):
                for inner in inner_hooks:
                    if isinstance(inner, dict) and "command" in inner:
                        commands.append(inner["command"])
        elif isinstance(entry, str):
            commands.append(entry)
    return commands


class TestHooksJsonExists:
    def test_hooks_json_exists_and_parses(self) -> None:
        """hooks/hooks.json must exist and be valid JSON."""
        if not HOOKS_JSON_PATH.exists():
            pytest.skip("Phase B artifact hooks/hooks.json not yet created")
        data = json.loads(HOOKS_JSON_PATH.read_text())
        assert isinstance(data, dict)


class TestHooksJsonStructure:
    @pytest.fixture()
    def hooks_data(self) -> dict:
        if not HOOKS_JSON_PATH.exists():
            pytest.skip("Phase B artifact hooks/hooks.json not yet created")
        return json.loads(HOOKS_JSON_PATH.read_text())

    def test_hooks_json_has_top_level_hooks_key(self, hooks_data: dict) -> None:
        """Schema must be {'hooks': {...}} with a top-level 'hooks' key."""
        assert "hooks" in hooks_data, (
            "hooks.json must have a top-level 'hooks' key"
        )

    def test_hooks_json_covers_all_31_registrations(self, hooks_data: dict) -> None:
        """Total registrations across all event keys must equal 31."""
        registrations = _collect_all_registrations(hooks_data)
        assert len(registrations) == 31, (
            f"hooks.json must have 31 total registrations to match templates/settings.json, "
            f"found {len(registrations)}"
        )

    def test_hooks_json_event_mapping(self, hooks_data: dict) -> None:
        """Each expected event must have its expected script names present in command strings."""
        hooks_section = hooks_data.get("hooks", {})
        for event, expected_scripts in EXPECTED_EVENT_SCRIPTS.items():
            assert event in hooks_section, (
                f"hooks.json must have an entry for event '{event}'"
            )
            event_entries = hooks_section[event]
            all_commands = " ".join(_collect_event_commands(event_entries))
            for script in expected_scripts:
                assert script in all_commands, (
                    f"Event '{event}' must reference script '{script}'"
                )

    def test_hooks_json_paths_use_claude_plugin_root(self, hooks_data: dict) -> None:
        """Every command must contain ${CLAUDE_PLUGIN_ROOT} (no hardcoded paths, no $HOME, no $WRIT_DIR)."""
        commands = _collect_all_commands(hooks_data)
        for command in commands:
            assert "${CLAUDE_PLUGIN_ROOT}" in command, (
                f"Command does not use ${{CLAUDE_PLUGIN_ROOT}}: {command!r}"
            )
            assert "$HOME" not in command, (
                f"Command must not hardcode $HOME: {command!r}"
            )
            assert "$WRIT_DIR" not in command, (
                f"Command must not use $WRIT_DIR: {command!r}"
            )


class TestHooksJsonPhaseC:
    """SessionStart bootstrap entry is added in Phase C."""

    @pytest.fixture()
    def hooks_data(self) -> dict:
        if not HOOKS_JSON_PATH.exists():
            pytest.skip("Phase B/C artifact hooks/hooks.json not yet created")
        return json.loads(HOOKS_JSON_PATH.read_text())

    def test_hooks_json_session_start_bootstrap_registered(self, hooks_data: dict) -> None:
        """Phase C: SessionStart event must map to hooks/scripts/session-start-bootstrap.sh."""
        hooks_section = hooks_data.get("hooks", {})
        if "SessionStart" not in hooks_section:
            pytest.skip("Phase C: SessionStart entry not yet added to hooks.json")
        entries = hooks_section["SessionStart"]
        all_commands = " ".join(_collect_event_commands(entries))
        assert "session-start-bootstrap.sh" in all_commands, (
            "SessionStart event must reference session-start-bootstrap.sh"
        )


class TestHookScriptFiles:
    @pytest.fixture()
    def hooks_data(self) -> dict:
        if not HOOKS_JSON_PATH.exists():
            pytest.skip("Phase B artifact hooks/hooks.json not yet created")
        return json.loads(HOOKS_JSON_PATH.read_text())

    def test_hook_scripts_exist_for_every_registration(self, hooks_data: dict) -> None:
        """Every command path in hooks.json must resolve to an existing .sh file on disk."""
        commands = _collect_all_commands(hooks_data)
        missing = []
        for command in commands:
            # Extract the script path portion (last token that ends in .sh)
            tokens = command.split()
            for token in tokens:
                if token.endswith(".sh") and "${CLAUDE_PLUGIN_ROOT}" in token:
                    resolved = _expand_plugin_root(token, REPO_ROOT)
                    if not resolved.exists():
                        missing.append(str(resolved))
        assert not missing, (
            f"The following hook scripts referenced in hooks.json do not exist:\n"
            + "\n".join(missing)
        )

    def test_hook_scripts_are_executable(self, hooks_data: dict) -> None:
        """Every hook script referenced in hooks.json must have the executable bit set."""
        commands = _collect_all_commands(hooks_data)
        not_executable = []
        for command in commands:
            tokens = command.split()
            for token in tokens:
                if token.endswith(".sh") and "${CLAUDE_PLUGIN_ROOT}" in token:
                    resolved = _expand_plugin_root(token, REPO_ROOT)
                    if resolved.exists() and not os.access(resolved, os.X_OK):
                        not_executable.append(str(resolved))
        assert not not_executable, (
            f"The following hook scripts are not executable:\n"
            + "\n".join(not_executable)
        )
