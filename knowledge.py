"""Knowledge base grep tool for the read-screen-tool application."""

import re
from pathlib import Path
from typing import Dict, List, Tuple


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

    txt_files: List[Path] = list(knowledge_path.glob("*.txt"))
    txt_files.extend(knowledge_path.glob("*/*.txt"))

    if not txt_files:
        return "No matches found."

    pattern_lower = pattern.lower()
    results: List[str] = []
    total_matches = 0

    for txt_file in sorted(txt_files):
        if total_matches >= max_results:
            break

        try:
            lines = txt_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        file_matches: List[Tuple[int, str]] = []
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


def get_grep_tool_definition() -> Dict:
    """Return an OpenAI-compatible function tool definition for grep_knowledge.

    Returns:
        A dict defining the function tool for use with OpenAI function calling.
    """
    return {
        "type": "function",
        "function": {
            "name": "grep_knowledge",
            "description": "Search text files in the knowledge base using grep. Returns matching lines with context.",
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
