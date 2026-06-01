"""Tests for ingest format selection."""

from textual.widgets import Select

from kg_world_anvil.tui.screens.ingest import resolve_text_format
from kg_world_anvil.models import TextFormat


class _FakeSelect:
    def __init__(self, value):
        self.value = value


def test_resolve_text_format_auto_and_null():
    assert resolve_text_format(_FakeSelect("auto")) is None
    assert resolve_text_format(_FakeSelect(Select.NULL)) is None


def test_resolve_text_format_specific():
    assert resolve_text_format(_FakeSelect("markdown")) == TextFormat.MARKDOWN
