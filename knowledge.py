"""Knowledge base tools for the read-screen-tool application.

Provides:
- ``grep_knowledge``: Search text files in the knowledge base.
- ``read_file``: Read a file from allowed directories (knowledge, memory).
- ``write_file``: Write a file to allowed directories (knowledge, memory).
"""

from __future__ import annotations

import re
from pathlib import Path

# Supported file extensions and their search strategies
_STRUCTURED_EXTENSIONS = {".md", ".tex"}
_TEXT_EXTENSIONS = {".txt"}
_ALL_EXTENSIONS = _STRUCTURED_EXTENSIONS | _TEXT_EXTENSIONS


def _validate_path(file_path: str, allowed_dirs: list[Path]) -> Path | None:
    """Validate that a file path is within one of the allowed directories.

    Prevents path traversal attacks (e.g. ``../`` escaping).

    Args:
        file_path: The relative file path to validate.
        allowed_dirs: List of allowed base directories (resolved).

    Returns:
        The resolved absolute Path if valid, or None if invalid.
    """
    try:
        valid_candidate: Path | None = None

        # Check if the resolved path is under any allowed directory
        for base_dir in allowed_dirs:
            base_resolved = base_dir.resolve()
            candidate = (base_resolved / file_path).resolve()
            # Check that candidate is under base_resolved (not equal or above)
            try:
                candidate.relative_to(base_resolved)
                # Prefer the directory where the file actually exists
                if candidate.exists():
                    return candidate
                # Keep the first valid candidate as fallback
                if valid_candidate is None:
                    valid_candidate = candidate
            except ValueError:
                continue

        return valid_candidate  # None if path traversal detected
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Section parsing for structured documents
# ---------------------------------------------------------------------------

# Markdown heading patterns
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# LaTeX section commands (in order of depth)
_TEX_SECTION_COMMANDS: list[tuple[str, int]] = [
    ("\\part", 0),
    ("\\chapter", 1),
    ("\\section", 2),
    ("\\subsection", 3),
    ("\\subsubsection", 4),
    ("\\paragraph", 5),
    ("\\subparagraph", 6),
]


def _parse_md_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split markdown content into sections based on headings.

    Each section starts at a heading line and continues until the next
    heading of equal or higher level, or end of file.

    Args:
        lines: List of text lines.

    Returns:
        List of ``(heading, body_lines)`` tuples. Lines before the first
        heading are returned with an empty heading string.
    """
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_body: list[str] = []
    current_level = 7  # sentinel: lower than any real heading

    for line in lines:
        m = _MD_HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            # If this heading is same or higher level, start a new section
            if level <= current_level:
                if current_body or current_heading:
                    sections.append((current_heading, current_body))
                current_heading = line.rstrip()
                current_body = []
                current_level = level
            else:
                # Sub-heading: keep accumulating in same section
                current_body.append(line)
        else:
            current_body.append(line)

    # Don't forget the last section
    if current_body or current_heading:
        sections.append((current_heading, current_body))

    return sections


def _parse_tex_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split LaTeX content into sections based on section commands.

    Each section starts at a \\section/\\subsection/etc. command and
    continues until the next command of equal or higher level, or end of file.

    Args:
        lines: List of text lines.

    Returns:
        List of ``(heading, body_lines)`` tuples. Lines before the first
        section command are returned with an empty heading string.
    """
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_body: list[str] = []
    current_level = 99  # sentinel: higher than any real section level

    for line in lines:
        stripped = line.strip()
        matched_level = None

        # Check if this line starts with a section command
        # Handles both \section{Title} and \section[Short]{Title}
        for cmd, level in _TEX_SECTION_COMMANDS:
            if re.match(re.escape(cmd) + r"(\[.*?\])?\s*\{", stripped):
                matched_level = level
                break

        if matched_level is not None and matched_level <= current_level:
            # New section at same or higher level
            if current_body or current_heading:
                sections.append((current_heading, current_body))
            current_heading = line.rstrip()
            current_body = []
            current_level = matched_level
        else:
            current_body.append(line)

    # Don't forget the last section
    if current_body or current_heading:
        sections.append((current_heading, current_body))

    return sections


def _search_structured_file(
    file_path: Path,
    pattern_lower: str,
    max_results: int,
) -> list[str]:
    """Search a structured file (md/tex) and return matching sections.

    For each line matching the pattern, the entire containing section
    (heading + body) is returned. Duplicate sections are deduplicated.

    Args:
        file_path: Path to the file.
        pattern_lower: Lowercase search pattern.
        max_results: Maximum number of matching sections to return.

    Returns:
        List of formatted result blocks.
    """
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    # Parse into sections based on file type
    suffix = file_path.suffix.lower()
    if suffix == ".md":
        sections = _parse_md_sections(lines)
    elif suffix == ".tex":
        sections = _parse_tex_sections(lines)
    else:
        return []

    results: list[str] = []
    seen_sections: set[int] = set()  # track section indices to deduplicate

    for idx, (heading, body) in enumerate(sections):
        if len(results) >= max_results:
            break

        # Check if any line in this section matches
        all_lines = [heading] + body if heading else body
        for line in all_lines:
            if pattern_lower in line.lower():
                if idx not in seen_sections:
                    seen_sections.add(idx)
                    # Format the section
                    section_text = "\n".join(all_lines).strip()
                    block = (
                        f"File: {file_path.name}, Section: {heading or '(beginning)'}\n"
                        f"{section_text}\n"
                        f"---"
                    )
                    results.append(block)
                break  # one match per section is enough

    return results


def _search_text_file(
    file_path: Path,
    pattern_lower: str,
    max_results: int,
    context_lines: int,
) -> list[str]:
    """Search a plain text file and return matching lines with context.

    Args:
        file_path: Path to the file.
        pattern_lower: Lowercase search pattern.
        max_results: Maximum number of matches to return.
        context_lines: Number of surrounding context lines.

    Returns:
        List of formatted result blocks.
    """
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    results: list[str] = []
    for i, line in enumerate(lines):
        if len(results) >= max_results:
            break

        if pattern_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)

            context_before = lines[start:i]
            context_after = lines[i + 1 : end]

            before_str = "\n".join(context_before)
            after_str = "\n".join(context_after)
            block = (
                f"File: {file_path.name}, Line {i + 1}:\n"
                f"{before_str}\n"
                f">>> {line}\n"
                f"{after_str}\n"
                f"---"
            )
            results.append(block)

    return results


def grep_knowledge(
    pattern: str,
    max_results: int = 20,
    context_lines: int = 2,
    knowledge_dir: str = "knowledge",
) -> str:
    """Search files in the knowledge base.

    Supports three strategies based on file type:
    - **.md files**: Return the entire section (heading → next heading) containing matches.
    - **.tex files**: Return the entire section (\\section → next \\section) containing matches.
    - **.txt files**: Return matching lines with surrounding context lines.

    Args:
        pattern: The text pattern to search for (case-insensitive).
        max_results: Maximum number of results to return (default: 20).
        context_lines: Number of surrounding context lines for .txt files (default: 2).
        knowledge_dir: Path to the knowledge directory (default: "knowledge").

    Returns:
        A formatted string with matching content, or an error message.
    """
    knowledge_path = Path(knowledge_dir)

    if not knowledge_path.is_dir():
        return "Knowledge directory not found."

    # Collect all supported files
    all_files: list[Path] = []
    for ext in _ALL_EXTENSIONS:
        all_files.extend(knowledge_path.glob(f"*{ext}"))
        all_files.extend(knowledge_path.glob(f"*/*{ext}"))

    if not all_files:
        return "No matches found."

    pattern_lower = pattern.lower()
    results: list[str] = []

    # Process structured files first (md, tex), then text files
    structured_files = sorted(f for f in all_files if f.suffix.lower() in _STRUCTURED_EXTENSIONS)
    text_files = sorted(f for f in all_files if f.suffix.lower() in _TEXT_EXTENSIONS)

    for file_path in structured_files:
        if len(results) >= max_results:
            break
        file_results = _search_structured_file(file_path, pattern_lower, max_results - len(results))
        results.extend(file_results)

    for file_path in text_files:
        if len(results) >= max_results:
            break
        file_results = _search_text_file(
            file_path, pattern_lower, max_results - len(results), context_lines
        )
        results.extend(file_results)

    if not results:
        return "No matches found."

    return "\n".join(results)


def get_grep_tool_definition() -> dict:
    """Return an OpenAI-compatible function tool definition for grep_knowledge.

    Returns:
        A dict defining the function tool for use with OpenAI function calling.
    """
    return {
        "type": "function",
        "function": {
            "name": "grep_knowledge",
            "description": (
                "Search files in the knowledge base. "
                "For .md and .tex files, returns the entire section containing the match. "
                "For .txt files, returns matching lines with surrounding context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The text pattern to search for (case-insensitive)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 20)",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": (
                            "Number of surrounding context lines for .txt files (default: 2). "
                            "Ignored for .md and .tex files which return full sections."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    }


# ---------------------------------------------------------------------------
# File read/write tools
# ---------------------------------------------------------------------------


def read_file(
    file_path: str,
    allowed_dirs: list[str] | None = None,
) -> str:
    """Read a file from one of the allowed directories.

    Args:
        file_path: Relative path to the file (e.g. "notes/todo.txt").
        allowed_dirs: List of allowed directory paths as strings.
            Defaults to ["knowledge", "memory"].

    Returns:
        The file contents as a string, or an error message.
    """
    if allowed_dirs is None:
        allowed_dirs = ["knowledge", "memory"]

    bases = [Path(d) for d in allowed_dirs]
    resolved = _validate_path(file_path, bases)

    if resolved is None:
        return (
            f"Error: Path '{file_path}' is not within allowed directories: "
            f"{', '.join(allowed_dirs)}"
        )

    if not resolved.is_file():
        return f"Error: File not found: {file_path}"

    try:
        content = resolved.read_text(encoding="utf-8")
        return content
    except UnicodeDecodeError:
        return f"Error: File '{file_path}' is not a valid text file (UTF-8 decode failed)."
    except OSError as e:
        return f"Error reading file '{file_path}': {e}"


def write_file(
    file_path: str,
    content: str,
    allowed_dirs: list[str] | None = None,
) -> str:
    """Write content to a file in one of the allowed directories.

    Creates parent directories if they don't exist.

    Args:
        file_path: Relative path to the file (e.g. "memory/notes/todo.txt").
        content: The text content to write.
        allowed_dirs: List of allowed directory paths as strings.
            Defaults to ["knowledge", "memory"].

    Returns:
        A success message, or an error message.
    """
    if allowed_dirs is None:
        allowed_dirs = ["knowledge", "memory"]

    bases = [Path(d) for d in allowed_dirs]
    resolved = _validate_path(file_path, bases)

    if resolved is None:
        return (
            f"Error: Path '{file_path}' is not within allowed directories: "
            f"{', '.join(allowed_dirs)}"
        )

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to '{file_path}'."
    except OSError as e:
        return f"Error writing file '{file_path}': {e}"


def get_read_file_tool_definition() -> dict:
    """Return an OpenAI-compatible function tool definition for read_file."""
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a text file. "
                "Only files in the knowledge/ or memory/ directories are accessible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Relative path to the file, e.g. 'notes/todo.txt'. "
                            "Must be within knowledge/ or memory/."
                        ),
                    },
                },
                "required": ["file_path"],
            },
        },
    }


def get_write_file_tool_definition() -> dict:
    """Return an OpenAI-compatible function tool definition for write_file."""
    return {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write text content to a file. "
                "Only knowledge/ and memory/ directories are accessible. "
                "Creates parent directories if needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Relative path to the file, e.g. 'memory/notes/todo.txt'. "
                            "Must be within knowledge/ or memory/."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content to write to the file.",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    }
