"""Knowledge base tools for the read-screen-tool application.

Provides:
- ``grep_knowledge``: Search text files in the knowledge base.
- ``read_file``: Read a file from allowed directories (knowledge, memory).
- ``write_file``: Write a file to allowed directories (knowledge, memory).
"""

from __future__ import annotations

from pathlib import Path


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


def grep_knowledge(
    pattern: str,
    max_results: int = 20,
    context_lines: int = 2,
    knowledge_dir: str = "knowledge",
) -> str:
    """Search text files in the knowledge base using grep.

    Args:
        pattern: The text pattern to search for (case-insensitive).
        max_results: Maximum number of results to return (default: 20).
        context_lines: Number of surrounding context lines (default: 2).
        knowledge_dir: Path to the knowledge directory (default: "knowledge").

    Returns:
        A formatted string with matching lines and context, or an error message.
    """
    knowledge_path = Path(knowledge_dir)

    if not knowledge_path.is_dir():
        return "Knowledge directory not found."

    txt_files: list[Path] = list(knowledge_path.glob("*.txt"))
    txt_files.extend(knowledge_path.glob("*/*.txt"))

    if not txt_files:
        return "No matches found."

    pattern_lower = pattern.lower()
    results: list[str] = []
    total_matches = 0

    for txt_file in sorted(txt_files):
        if total_matches >= max_results:
            break

        try:
            lines = txt_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        file_matches: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            if pattern_lower in line.lower():
                file_matches.append((i, line))
                total_matches += 1
                if total_matches >= max_results:
                    break

        for line_num, matching_line in file_matches:
            start = max(0, line_num - context_lines)
            end = min(len(lines), line_num + context_lines + 1)

            context_before = lines[start:line_num]
            context_after = lines[line_num + 1 : end]

            before_str = "\n".join(context_before)
            after_str = "\n".join(context_after)
            block = (
                f"File: {txt_file.name}, Line {line_num + 1}:\n"
                f"{before_str}\n"
                f">>> {matching_line}\n"
                f"{after_str}\n"
                f"---"
            )
            results.append(block)

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
                "Search text files in the knowledge base using grep. "
                "Returns matching lines with context."
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
                        "description": "Number of surrounding context lines (default: 2)",
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
