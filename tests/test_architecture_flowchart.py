"""Structural validation for writ-architecture-flowchart.html.

The artifact is static documentation. These tests confirm the file exists,
is non-empty, and exposes the eight architectural layers the CEO presentation
relies on. No runtime behavior is asserted.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLOWCHART_PATH = PROJECT_ROOT / "writ-architecture-flowchart.html"

REQUIRED_LAYER_IDS = {
    "layer-pipeline",
    "layer-enforcement",
    "layer-graph",
    "layer-modes",
    "layer-phases",
    "layer-evolution",
    "layer-split",
    "layer-weights",
}


class LayerCardCollector(HTMLParser):
    """Collect data-layer-id attributes on .layer-card elements."""

    def __init__(self) -> None:
        super().__init__()
        self.layer_ids: set[str] = set()
        self.summaries_seen: set[str] = set()
        self.details_seen: set[str] = set()
        self._stack: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        self._stack.append((tag, attr_map))
        classes = attr_map.get("class", "").split()
        layer_id = attr_map.get("data-layer-id", "")
        if "layer-card" in classes and layer_id:
            self.layer_ids.add(layer_id)
        if "layer-summary" in classes:
            owner = self._find_owning_layer()
            if owner:
                self.summaries_seen.add(owner)
        if "layer-detail" in classes:
            owner = self._find_owning_layer()
            if owner:
                self.details_seen.add(owner)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i]
                break

    def _find_owning_layer(self) -> str | None:
        for _, attrs in reversed(self._stack):
            layer_id = attrs.get("data-layer-id")
            if layer_id:
                return layer_id
        return None


@pytest.fixture(scope="module")
def html_text() -> str:
    assert FLOWCHART_PATH.exists(), f"missing artifact: {FLOWCHART_PATH}"
    return FLOWCHART_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(html_text: str) -> LayerCardCollector:
    parser = LayerCardCollector()
    parser.feed(html_text)
    return parser


def test_file_non_empty(html_text: str) -> None:
    assert len(html_text) > 5000, "flowchart should be a substantial single-file doc"


def test_has_doctype(html_text: str) -> None:
    assert html_text.lstrip().lower().startswith("<!doctype html>")


def test_contains_inline_script(html_text: str) -> None:
    assert "<script" in html_text, "interactivity requires an inline <script> block"


def test_no_external_assets(html_text: str) -> None:
    # No <link rel="stylesheet" href="http..."> and no <script src="http...">
    external_link = re.search(r'<link[^>]+href=[\'"]https?://', html_text, re.I)
    external_script = re.search(r'<script[^>]+src=[\'"]https?://', html_text, re.I)
    assert external_link is None, "no external CSS allowed (single-file artifact)"
    assert external_script is None, "no external JS allowed (single-file artifact)"


def test_eight_layer_cards_present(parsed: LayerCardCollector) -> None:
    missing = REQUIRED_LAYER_IDS - parsed.layer_ids
    assert not missing, f"missing layer cards: {missing}"


def test_each_layer_has_summary(parsed: LayerCardCollector) -> None:
    missing = REQUIRED_LAYER_IDS - parsed.summaries_seen
    assert not missing, f"layers missing .layer-summary: {missing}"


def test_each_layer_has_detail(parsed: LayerCardCollector) -> None:
    missing = REQUIRED_LAYER_IDS - parsed.details_seen
    assert not missing, f"layers missing .layer-detail: {missing}"


def test_weighting_numbers_cited(html_text: str) -> None:
    for weight in ("0.198", "0.594", "0.099", "0.01"):
        assert weight in html_text, f"missing weight {weight} in artifact"


def test_pipeline_stages_named(html_text: str) -> None:
    for term in ("BM25", "Tantivy", "hnswlib", "FalkorDB", "RRF"):
        assert term in html_text, f"missing pipeline term {term}"
