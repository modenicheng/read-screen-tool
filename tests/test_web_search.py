"""Tests for the web search tool."""

import json
from unittest.mock import MagicMock, patch

from web_search import get_web_search_tool_definition, web_search


def _mock_ddg_response(
    heading: str = "",
    abstract: str = "",
    abstract_url: str = "",
    answer: str = "",
    definition: str = "",
    definition_url: str = "",
    related_topics: list[dict] | None = None,
    results: list[dict] | None = None,
) -> dict:
    """Build a mock DuckDuckGo API response dict."""
    return {
        "Heading": heading,
        "AbstractText": abstract,
        "AbstractURL": abstract_url,
        "Answer": answer,
        "Definition": definition,
        "DefinitionURL": definition_url,
        "RelatedTopics": related_topics or [],
        "Results": results or [],
    }


class TestWebSearch:
    """Tests for web_search()."""

    @patch("web_search.urllib.request.urlopen")
    def test_returns_heading_with_abstract(self, mock_urlopen: MagicMock) -> None:
        """Verify abstract result is formatted as Title/URL/Snippet."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            heading="Python",
            abstract="Python is a programming language.",
            abstract_url="https://en.wikipedia.org/wiki/Python",
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("Python")

        assert "Python" in result
        assert "https://en.wikipedia.org/wiki/Python" in result
        assert "Python is a programming language." in result
        assert "---" in result

    @patch("web_search.urllib.request.urlopen")
    def test_returns_related_topics(self, mock_urlopen: MagicMock) -> None:
        """Verify RelatedTopics are formatted as Text/URL pairs."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            related_topics=[
                {"Text": "Topic A", "FirstURL": "https://a.com"},
                {"Text": "Topic B", "FirstURL": "https://b.com"},
            ]
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("test query", max_results=5)

        assert "Topic A" in result
        assert "https://a.com" in result
        assert "Topic B" in result
        assert "https://b.com" in result

    @patch("web_search.urllib.request.urlopen")
    def test_returns_results(self, mock_urlopen: MagicMock) -> None:
        """Verify Results are formatted as Text/URL pairs."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            results=[
                {"Text": "Result 1", "FirstURL": "https://r1.com"},
                {"Text": "Result 2", "FirstURL": "https://r2.com"},
            ]
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("test query")

        assert "Result 1" in result
        assert "https://r1.com" in result
        assert "Result 2" in result
        assert "https://r2.com" in result

    @patch("web_search.urllib.request.urlopen")
    def test_no_results(self, mock_urlopen: MagicMock) -> None:
        """Verify completely empty response returns 'No results found.'."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response()).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("nonexistent")

        assert result == "No results found."

    @patch("web_search.urllib.request.urlopen")
    def test_respects_max_results(self, mock_urlopen: MagicMock) -> None:
        """Verify max_results limits total output entries."""
        topics = [{"Text": f"Topic {i}", "FirstURL": f"https://t{i}.com"} for i in range(10)]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            related_topics=topics,
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("test", max_results=3)

        # Should only have 3 topics
        assert "Topic 0" in result
        assert "Topic 2" in result
        assert "Topic 3" not in result

    @patch("web_search.urllib.request.urlopen")
    def test_error_handling_urlerror(self, mock_urlopen: MagicMock) -> None:
        """Verify URLError is caught and returned as error string."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = web_search("test")

        assert result == "Error: Failed to reach DuckDuckGo: Connection refused"

    @patch("web_search.urllib.request.urlopen")
    def test_error_handling_timeout(self, mock_urlopen: MagicMock) -> None:
        """Verify timeout is caught and returned as error string."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        result = web_search("test")

        assert result == "Error: Web search failed: timed out"

    @patch("web_search.urllib.request.urlopen")
    def test_returns_answer(self, mock_urlopen: MagicMock) -> None:
        """Verify Answer field is included in output."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            answer="42",
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("ultimate answer")

        assert "Answer: 42" in result

    @patch("web_search.urllib.request.urlopen")
    def test_returns_definition(self, mock_urlopen: MagicMock) -> None:
        """Verify Definition field is formatted correctly."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_mock_ddg_response(
            definition="A high-level programming language.",
            definition_url="https://en.wikipedia.org/wiki/Python",
        )).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("Python definition")

        assert "Definition" in result
        assert "A high-level programming language." in result
        assert "https://en.wikipedia.org/wiki/Python" in result

    @patch("web_search.urllib.request.urlopen")
    def test_json_decode_error(self, mock_urlopen: MagicMock) -> None:
        """Verify JSON decode error is caught and returned as error string."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = web_search("test")

        assert result.startswith("Error: Web search failed:")


class TestGetWebSearchToolDefinition:
    """Tests for get_web_search_tool_definition()."""

    def test_returns_dict(self) -> None:
        definition = get_web_search_tool_definition()
        assert isinstance(definition, dict)

    def test_type_is_function(self) -> None:
        definition = get_web_search_tool_definition()
        assert definition["type"] == "function"

    def test_function_name(self) -> None:
        definition = get_web_search_tool_definition()
        assert definition["function"]["name"] == "web_search"

    def test_has_description(self) -> None:
        definition = get_web_search_tool_definition()
        desc = definition["function"]["description"]
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_parameters_type_is_object(self) -> None:
        definition = get_web_search_tool_definition()
        assert definition["function"]["parameters"]["type"] == "object"

    def test_query_property(self) -> None:
        definition = get_web_search_tool_definition()
        props = definition["function"]["parameters"]["properties"]
        assert "query" in props
        assert props["query"]["type"] == "string"

    def test_max_results_property(self) -> None:
        definition = get_web_search_tool_definition()
        props = definition["function"]["parameters"]["properties"]
        assert "max_results" in props
        assert props["max_results"]["type"] == "integer"

    def test_query_is_required(self) -> None:
        definition = get_web_search_tool_definition()
        required = definition["function"]["parameters"]["required"]
        assert "query" in required
        assert len(required) == 1

    def test_max_results_not_required(self) -> None:
        definition = get_web_search_tool_definition()
        required = definition["function"]["parameters"]["required"]
        assert "max_results" not in required
