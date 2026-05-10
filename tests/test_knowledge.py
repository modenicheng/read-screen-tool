"""Tests for the knowledge base grep tool."""

from collections.abc import Generator
from pathlib import Path

import pytest

from knowledge import get_grep_tool_definition, grep_knowledge


@pytest.fixture
def real_knowledge_dir() -> str:
    """Return the path to the real knowledge directory."""
    return str(Path(__file__).resolve().parent.parent / "knowledge")


@pytest.fixture
def temp_knowledge_dir(tmp_path: Path) -> Generator[Path]:
    """Create a temporary knowledge directory with a test file."""
    d = tmp_path / "knowledge"
    d.mkdir()
    file = d / "test.txt"
    file.write_text(
        "The quick brown fox jumps over the lazy dog.\n"
        "The lazy dog sleeps all day.\n"
        "Quick brown foxes are fast.\n"
        "SLOW TURTLES ARE NOT QUICK.\n"
        "This line has nothing.\n",
        encoding="utf-8",
    )
    yield d


@pytest.fixture
def temp_multi_file_dir(tmp_path: Path) -> Generator[Path]:
    """Create a temporary knowledge directory with multiple files."""
    d = tmp_path / "multi_knowledge"
    d.mkdir()
    f1 = d / "colors.txt"
    f1.write_text("red\nblue\ngreen\nyellow\n", encoding="utf-8")
    f2 = d / "animals.txt"
    f2.write_text("cat\ndog\nbird\nfish\n", encoding="utf-8")
    f3 = d / "empty.txt"
    f3.write_text("", encoding="utf-8")
    yield d


class TestGrepKnowledge:
    """Tests for grep_knowledge()."""

    def test_grep_finds_single_match(self, real_knowledge_dir: str) -> None:
        """Search for a word known to exist in 如何阅读一本书.txt."""
        result = grep_knowledge("主动", knowledge_dir=real_knowledge_dir)
        assert "No matches found." not in result
        assert "File: 如何阅读一本书.txt" in result
        assert ">>>" in result
        # "主动" appears in "主动的阅读" section
        assert "主动" in result

    def test_grep_returns_context_lines(self, real_knowledge_dir: str) -> None:
        """Verify context before and after the matching line appears."""
        # Search for something with known context
        result = grep_knowledge("主动的阅读", knowledge_dir=real_knowledge_dir)
        assert "File: 如何阅读一本书.txt" in result
        # Should have lines before the match
        lines = result.split("\n")
        # Find the line with >>>
        match_line_idx = next(i for i, line in enumerate(lines) if ">>>" in line)
        # There should be context lines before (non-empty)
        assert match_line_idx > 1  # File line info + at least one context line

    def test_grep_no_match(self, real_knowledge_dir: str) -> None:
        """Search for a nonsense string, verify 'No matches found.'."""
        result = grep_knowledge("zzzznonsensezzzz", knowledge_dir=real_knowledge_dir)
        assert result == "No matches found."

    def test_grep_case_insensitive(self, temp_knowledge_dir: Path) -> None:
        """Search lowercase and uppercase variants both match."""
        result_lower = grep_knowledge("quick", knowledge_dir=str(temp_knowledge_dir))
        result_upper = grep_knowledge("QUICK", knowledge_dir=str(temp_knowledge_dir))
        result_mixed = grep_knowledge("Quick", knowledge_dir=str(temp_knowledge_dir))

        assert "No matches found." not in result_lower
        assert result_lower == result_upper == result_mixed
        # Should match "quick" (line 1), "Quick" (line 3), and "QUICK" (line 4)
        assert result_lower.count(">>>") == 3

    def test_grep_respects_max_results(self, temp_knowledge_dir: Path) -> None:
        """Set max_results=1, verify only 1 result."""
        result = grep_knowledge("quick", knowledge_dir=str(temp_knowledge_dir), max_results=1)
        assert result.count(">>>") == 1

    def test_grep_missing_directory(self) -> None:
        """Point to a nonexistent directory, verify error message."""
        result = grep_knowledge("anything", knowledge_dir="nonexistent_dir_xyz")
        assert result == "Knowledge directory not found."

    def test_grep_multiple_files(self, temp_multi_file_dir: Path) -> None:
        """Search across multiple files."""
        result = grep_knowledge("dog", knowledge_dir=str(temp_multi_file_dir))
        assert "No matches found." not in result
        assert result.count(">>>") >= 1
        assert "File: animals.txt" in result


class TestGetGrepToolDefinition:
    """Tests for get_grep_tool_definition()."""

    def test_get_tool_definition(self) -> None:
        """Verify the returned dict has correct structure."""
        definition = get_grep_tool_definition()

        assert isinstance(definition, dict)
        assert definition["type"] == "function"

        func = definition["function"]
        assert func["name"] == "grep_knowledge"
        assert isinstance(func["description"], str)
        assert len(func["description"]) > 0

        params = func["parameters"]
        assert params["type"] == "object"

        props = params["properties"]
        assert "pattern" in props
        assert props["pattern"]["type"] == "string"

        assert "max_results" in props
        assert props["max_results"]["type"] == "integer"

        assert "context_lines" in props
        assert props["context_lines"]["type"] == "integer"

        assert "pattern" in params["required"]
        assert len(params["required"]) == 1
