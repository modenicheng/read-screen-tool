"""Tests for the knowledge base grep tool."""

from collections.abc import Generator
from pathlib import Path

import pytest

from knowledge import (
    get_grep_tool_definition,
    get_read_file_tool_definition,
    get_write_file_tool_definition,
    grep_knowledge,
    read_file,
    write_file,
)


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


@pytest.fixture
def temp_md_dir(tmp_path: Path) -> Generator[Path]:
    """Create a temporary knowledge directory with a markdown file."""
    d = tmp_path / "md_knowledge"
    d.mkdir()
    file = d / "notes.md"
    file.write_text(
        "# Introduction\n"
        "This is the intro section.\n"
        "It contains general information.\n"
        "\n"
        "## Getting Started\n"
        "First, install the dependencies.\n"
        "Then run the application.\n"
        "\n"
        "## Advanced Usage\n"
        "For advanced users, you can customize settings.\n"
        "Edit the config.yaml file.\n"
        "\n"
        "# Troubleshooting\n"
        "If you encounter errors, check the logs.\n"
        "Common issues include missing dependencies.\n",
        encoding="utf-8",
    )
    yield d


@pytest.fixture
def temp_tex_dir(tmp_path: Path) -> Generator[Path]:
    """Create a temporary knowledge directory with a LaTeX file."""
    d = tmp_path / "tex_knowledge"
    d.mkdir()
    file = d / "paper.tex"
    file.write_text(
        "\\section{Introduction}\n"
        "This paper discusses important topics.\n"
        "We present novel findings.\n"
        "\n"
        "\\subsection{Background}\n"
        "Previous work has shown various results.\n"
        "Our approach differs significantly.\n"
        "\n"
        "\\section{Methodology}\n"
        "We used a mixed-methods approach.\n"
        "Data was collected over six months.\n"
        "\n"
        "\\section{Results}\n"
        "The results support our hypothesis.\n"
        "Statistical analysis confirms significance.\n",
        encoding="utf-8",
    )
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


class TestGrepMarkdownSections:
    """Tests for markdown section-based search."""

    def test_md_returns_entire_section(self, temp_md_dir: Path) -> None:
        """Search in md file returns the entire section containing the match."""
        result = grep_knowledge("dependencies", knowledge_dir=str(temp_md_dir))
        assert "No matches found." not in result
        assert "File: notes.md" in result
        # Should return the "Getting Started" section
        assert "Getting Started" in result
        assert "install the dependencies" in result
        assert "run the application" in result

    def test_md_no_duplicate_sections(self, temp_md_dir: Path) -> None:
        """Multiple matches in same section return only one section."""
        result = grep_knowledge("section", knowledge_dir=str(temp_md_dir))
        # "section" appears in multiple places, but each section should appear once
        lines = result.split("\n")
        section_headers = [line for line in lines if line.startswith("Section:")]
        # Count unique section headers
        unique_headers = set(section_headers)
        assert len(section_headers) == len(unique_headers)

    def test_md_respects_max_results(self, temp_md_dir: Path) -> None:
        """max_results limits number of sections returned."""
        result = grep_knowledge("the", knowledge_dir=str(temp_md_dir), max_results=2)
        # Count section markers
        assert result.count("Section:") <= 2

    def test_md_case_insensitive(self, temp_md_dir: Path) -> None:
        """Search is case insensitive."""
        result_lower = grep_knowledge("introduction", knowledge_dir=str(temp_md_dir))
        result_upper = grep_knowledge("INTRODUCTION", knowledge_dir=str(temp_md_dir))
        assert result_lower == result_upper

    def test_md_subsection_match(self, temp_md_dir: Path) -> None:
        """Match in a subsection returns the subsection, not the parent section."""
        result = grep_knowledge("customize", knowledge_dir=str(temp_md_dir))
        assert "Advanced Usage" in result
        assert "customize settings" in result


class TestGrepTexSections:
    """Tests for LaTeX section-based search."""

    def test_tex_returns_entire_section(self, temp_tex_dir: Path) -> None:
        """Search in tex file returns the entire section containing the match."""
        result = grep_knowledge("mixed-methods", knowledge_dir=str(temp_tex_dir))
        assert "No matches found." not in result
        assert "File: paper.tex" in result
        assert "Methodology" in result
        assert "mixed-methods" in result
        assert "six months" in result

    def test_tex_subsection_returns_subsection(self, temp_tex_dir: Path) -> None:
        """Match in subsection returns the subsection, not parent section."""
        result = grep_knowledge("differs", knowledge_dir=str(temp_tex_dir))
        assert "Background" in result
        assert "differs significantly" in result

    def test_tex_respects_max_results(self, temp_tex_dir: Path) -> None:
        """max_results limits number of sections returned."""
        result = grep_knowledge("the", knowledge_dir=str(temp_tex_dir), max_results=1)
        assert result.count("Section:") <= 1

    def test_tex_case_insensitive(self, temp_tex_dir: Path) -> None:
        """Search is case insensitive."""
        result_lower = grep_knowledge("methodology", knowledge_dir=str(temp_tex_dir))
        result_upper = grep_knowledge("METHODOLOGY", knowledge_dir=str(temp_tex_dir))
        assert result_lower == result_upper

    def test_tex_no_match(self, temp_tex_dir: Path) -> None:
        """Search for nonexistent string returns no matches."""
        result = grep_knowledge("zzzznonsensezzzz", knowledge_dir=str(temp_tex_dir))
        assert result == "No matches found."

    def test_tex_optional_argument(self, tmp_path: Path) -> None:
        """Section with optional argument [short]{long} is detected."""
        d = tmp_path / "tex_opt"
        d.mkdir()
        file = d / "opt.tex"
        file.write_text(
            "\\section[Short Title]{Long Title Here}\n"
            "Content under the section.\n"
            "\\subsection{Sub}\n"
            "Sub content.\n",
            encoding="utf-8",
        )
        result = grep_knowledge("Content under", knowledge_dir=str(d))
        assert "No matches found." not in result
        assert "Long Title Here" in result
        assert "Content under the section." in result

    def test_tex_pre_heading_content(self, tmp_path: Path) -> None:
        """Content before first section command is searchable."""
        d = tmp_path / "tex_pre"
        d.mkdir()
        file = d / "pre.tex"
        file.write_text(
            "% Preamble\n"
            "\\documentclass{article}\n"
            "Some preamble text with keyword.\n"
            "\\begin{document}\n"
            "\\section{First}\n"
            "Section content.\n",
            encoding="utf-8",
        )
        result = grep_knowledge("preamble text", knowledge_dir=str(d))
        assert "No matches found." not in result
        assert "preamble text with keyword" in result


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


# ---------------------------------------------------------------------------
# Tests for read_file
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Create temporary knowledge and memory directories with test files."""
    knowledge = tmp_path / "knowledge"
    memory = tmp_path / "memory"
    knowledge.mkdir()
    memory.mkdir()

    (knowledge / "notes.txt").write_text("knowledge content", encoding="utf-8")
    (memory / "todo.txt").write_text("memory content", encoding="utf-8")
    (memory / "subdir").mkdir()
    (memory / "subdir" / "nested.txt").write_text("nested content", encoding="utf-8")

    return knowledge, memory


class TestReadFile:
    """Tests for read_file()."""

    def test_read_from_knowledge(self, temp_dirs: tuple[Path, Path]) -> None:
        """Read a file from the knowledge directory."""
        knowledge, memory = temp_dirs
        result = read_file("notes.txt", allowed_dirs=[str(knowledge), str(memory)])
        assert result == "knowledge content"

    def test_read_from_memory(self, temp_dirs: tuple[Path, Path]) -> None:
        """Read a file from the memory directory."""
        knowledge, memory = temp_dirs
        result = read_file("todo.txt", allowed_dirs=[str(knowledge), str(memory)])
        assert result == "memory content"

    def test_read_nested_file(self, temp_dirs: tuple[Path, Path]) -> None:
        """Read a file in a subdirectory."""
        knowledge, memory = temp_dirs
        result = read_file("subdir/nested.txt", allowed_dirs=[str(knowledge), str(memory)])
        assert result == "nested content"

    def test_read_nonexistent_file(self, temp_dirs: tuple[Path, Path]) -> None:
        """Reading a nonexistent file returns an error."""
        knowledge, memory = temp_dirs
        result = read_file("no_such_file.txt", allowed_dirs=[str(knowledge), str(memory)])
        assert "Error" in result
        assert "not found" in result.lower()

    def test_read_outside_allowed_dirs(self, temp_dirs: tuple[Path, Path]) -> None:
        """Path traversal attempt is rejected."""
        knowledge, memory = temp_dirs
        result = read_file("../../etc/passwd", allowed_dirs=[str(knowledge), str(memory)])
        assert "Error" in result
        assert "not within allowed" in result

    def test_read_absolute_path_rejected(self, temp_dirs: tuple[Path, Path]) -> None:
        """Absolute paths are rejected."""
        knowledge, memory = temp_dirs
        result = read_file("/etc/passwd", allowed_dirs=[str(knowledge), str(memory)])
        assert "Error" in result

    def test_read_default_dirs(self, tmp_path: Path) -> None:
        """Default allowed_dirs is ['knowledge', 'memory']."""
        # This will fail because 'knowledge' and 'memory' don't exist at cwd
        result = read_file("any_file.txt")
        assert "Error" in result


class TestWriteFile:
    """Tests for write_file()."""

    def test_write_to_memory(self, temp_dirs: tuple[Path, Path]) -> None:
        """Write a file to the memory directory."""
        knowledge, memory = temp_dirs
        result = write_file("output.txt", "hello world", allowed_dirs=[str(memory)])
        assert "Successfully wrote" in result
        assert (memory / "output.txt").read_text(encoding="utf-8") == "hello world"

    def test_write_to_knowledge(self, temp_dirs: tuple[Path, Path]) -> None:
        """Write a file to the knowledge directory."""
        knowledge, memory = temp_dirs
        result = write_file("new_note.txt", "note content", allowed_dirs=[str(knowledge)])
        assert "Successfully wrote" in result
        assert (knowledge / "new_note.txt").read_text(encoding="utf-8") == "note content"

    def test_write_creates_parent_dirs(self, temp_dirs: tuple[Path, Path]) -> None:
        """Write creates parent directories if they don't exist."""
        knowledge, memory = temp_dirs
        result = write_file("deep/nested/file.txt", "deep content", allowed_dirs=[str(memory)])
        assert "Successfully wrote" in result
        written = (memory / "deep" / "nested" / "file.txt").read_text(encoding="utf-8")
        assert written == "deep content"

    def test_write_outside_allowed_dirs(self, temp_dirs: tuple[Path, Path]) -> None:
        """Path traversal attempt is rejected."""
        knowledge, memory = temp_dirs
        result = write_file("../../etc/evil.txt", "bad", allowed_dirs=[str(knowledge), str(memory)])
        assert "Error" in result
        assert "not within allowed" in result

    def test_write_absolute_path_rejected(self, temp_dirs: tuple[Path, Path]) -> None:
        """Absolute paths are rejected."""
        knowledge, memory = temp_dirs
        result = write_file("/tmp/evil.txt", "bad", allowed_dirs=[str(knowledge), str(memory)])
        assert "Error" in result

    def test_write_overwrites_existing(self, temp_dirs: tuple[Path, Path]) -> None:
        """Writing to an existing file overwrites it."""
        knowledge, memory = temp_dirs
        write_file("todo.txt", "new content", allowed_dirs=[str(memory)])
        assert (memory / "todo.txt").read_text(encoding="utf-8") == "new content"


class TestGetReadFileToolDefinition:
    """Tests for get_read_file_tool_definition()."""

    def test_structure(self) -> None:
        """Verify the tool definition has correct structure."""
        definition = get_read_file_tool_definition()
        assert definition["type"] == "function"
        assert definition["function"]["name"] == "read_file"
        assert "file_path" in definition["function"]["parameters"]["properties"]
        assert "file_path" in definition["function"]["parameters"]["required"]


class TestGetWriteFileToolDefinition:
    """Tests for get_write_file_tool_definition()."""

    def test_structure(self) -> None:
        """Verify the tool definition has correct structure."""
        definition = get_write_file_tool_definition()
        assert definition["type"] == "function"
        assert definition["function"]["name"] == "write_file"
        props = definition["function"]["parameters"]["properties"]
        assert "file_path" in props
        assert "content" in props
        required = definition["function"]["parameters"]["required"]
        assert "file_path" in required
        assert "content" in required
