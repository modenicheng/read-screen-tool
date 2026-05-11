"""Web search tool for the read-screen-tool application.

Provides:
- ``web_search``: Search the web using the DuckDuckGo Instant Answer API.
- ``get_web_search_tool_definition``: Return the OpenAI-compatible tool definition.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


def web_search(query: str, max_results: int = 8) -> str:
    """Search the web using DuckDuckGo Instant Answer API and return formatted results.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default: 8).

    Returns:
        A formatted string with Title, URL, and Snippet for each result,
        separated by ``---``, or an error message.
    """
    encoded = urllib.parse.quote(query)
    url = (
        f"https://api.duckduckgo.com/?q={encoded}"
        f"&format=json&no_html=1&skip_disambig=1"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ReadScreenTool/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return f"Error: Failed to reach DuckDuckGo: {e.reason}"
    except (OSError, json.JSONDecodeError, TimeoutError) as e:
        return f"Error: Web search failed: {e}"

    formatted: list[str] = []

    # 1. Heading + AbstractText (main instant answer)
    heading = data.get("Heading", "").strip()
    abstract = data.get("AbstractText", "").strip()
    abstract_url = data.get("AbstractURL", "").strip()

    if heading or abstract:
        title = heading or f"DuckDuckGo: {query}"
        snippet = abstract or "(No summary available)"
        if abstract_url:
            formatted.append(f"{title}\n{abstract_url}\n{snippet}\n---")
        else:
            formatted.append(f"{title}\n{snippet}\n---")

    # 2. Answer (instant answer, e.g. calculator)
    answer = data.get("Answer", "").strip()
    if answer:
        formatted.append(f"Answer: {answer}")

    # 3. Definition
    definition = data.get("Definition", "").strip()
    definition_url = data.get("DefinitionURL", "").strip()
    if definition:
        if definition_url:
            formatted.append(f"Definition\n{definition_url}\n{definition}\n---")
        else:
            formatted.append(f"Definition\n{definition}\n---")

    # 4. RelatedTopics
    count = len(formatted)
    for topic in data.get("RelatedTopics", []):
        if not isinstance(topic, dict) or count >= max_results:
            break
        text = topic.get("Text", "").strip()
        first_url = topic.get("FirstURL", "").strip()
        if text:
            formatted.append(f"{text}\n{first_url}\n---")
            count += 1

    # 5. Results (external results)
    for result in data.get("Results", []):
        if not isinstance(result, dict) or count >= max_results:
            break
        text = result.get("Text", "").strip()
        first_url = result.get("FirstURL", "").strip()
        if text:
            formatted.append(f"{text}\n{first_url}\n---")
            count += 1

    if not formatted:
        return "No results found."

    return "\n".join(formatted)


def get_web_search_tool_definition() -> dict:
    """Return an OpenAI-compatible function tool definition for web_search.

    Returns:
        A dict defining the function tool for use with OpenAI function calling.
    """
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web using DuckDuckGo and return formatted results. "
                "Each result includes a title, URL, and text snippet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 8)",
                    },
                },
                "required": ["query"],
            },
        },
    }
