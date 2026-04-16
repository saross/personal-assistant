"""
Unit tests for scripts/lit-search.py.

Tests the parsing, normalisation, deduplication, and fallback logic
using mocked HTTP responses. Does not hit real APIs.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

# Add scripts directory to path so we can import lit-search as a module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Import with the hyphen-to-underscore trick
import importlib
lit_search = importlib.import_module("lit-search")


# ============================================================================
# Fixtures: realistic API response payloads
# ============================================================================


CROSSREF_WORK = {
    "message": {
        "DOI": "10.1371/journal.pcbi.1009041",
        "title": ["Ten simple rules for making a vocabulary FAIR"],
        "author": [
            {"given": "Simon J. D.", "family": "Cox"},
            {"given": "Alejandra N.", "family": "Gonzalez-Beltran"},
        ],
        "published-print": {"date-parts": [[2021, 6, 24]]},
        "is-referenced-by-count": 37,
        "abstract": "We present ten simple rules...",
        "reference": [
            {
                "DOI": "10.1038/sdata.2016.18",
                "article-title": "The FAIR Guiding Principles",
                "author": "Wilkinson",
                "year": "2016",
            },
            {
                "DOI": "10.1371/journal.pcbi.1004743",
                "article-title": "Ten Simple Rules for Bio-ontology",
                "author": "Malone",
                "year": "2016",
            },
            {
                "unstructured": "Some unstructured reference text",
            },
        ],
    }
}


S2_PAPER = {
    "paperId": "7e2451a298b1c5c6dd7c7c881861a8cb3621f6fa",
    "title": "Ten simple rules for making a vocabulary FAIR",
    "authors": [
        {"name": "Simon J. D. Cox"},
        {"name": "Alejandra N. Gonzalez-Beltran"},
    ],
    "year": 2021,
    "abstract": "We present ten simple rules...",
    "citationCount": 35,
    "referenceCount": 38,
    "fieldsOfStudy": ["Computer Science"],
    "publicationTypes": ["JournalArticle"],
    "externalIds": {"DOI": "10.1371/journal.pcbi.1009041"},
}


S2_PAPER_WITH_REFS = {
    **S2_PAPER,
    "references": [
        {
            "paperId": "abc123",
            "title": "The FAIR Guiding Principles",
            "authors": [{"name": "Mark D. Wilkinson"}],
            "year": 2016,
            "externalIds": {"DOI": "10.1038/sdata.2016.18"},
            "citationCount": 5000,
        },
        {
            "paperId": "def456",
            "title": "A unique S2 reference",
            "authors": [{"name": "Someone Else"}],
            "year": 2020,
            "externalIds": {"DOI": "10.9999/unique"},
            "citationCount": 10,
        },
    ],
}


S2_PAPER_WITH_CITATIONS = {
    **S2_PAPER,
    "citations": [
        {
            "paperId": "cit001",
            "title": "Citing paper A",
            "authors": [{"name": "Author A"}],
            "year": 2023,
            "externalIds": {"DOI": "10.9999/cit-a"},
            "citationCount": 50,
        },
        {
            "paperId": "cit002",
            "title": "Citing paper B",
            "authors": [{"name": "Author B"}],
            "year": 2024,
            "externalIds": {"DOI": "10.9999/cit-b"},
            "citationCount": 100,
        },
    ],
}


OPENALEX_WORK = {
    "id": "https://openalex.org/W3113245274",
    "doi": "https://doi.org/10.1371/journal.pcbi.1009041",
    "display_name": "Ten simple rules for making a vocabulary FAIR",
    "publication_year": 2021,
    "cited_by_count": 40,
    "authorships": [
        {"author": {"display_name": "Simon J. D. Cox"}},
        {"author": {"display_name": "Alejandra N. Gonzalez-Beltran"}},
    ],
    "open_access": {"is_oa": True, "oa_url": "https://doi.org/10.1371/..."},
    "abstract_inverted_index": {
        "We": [0],
        "present": [1],
        "ten": [2],
        "simple": [3],
        "rules": [4],
    },
    "referenced_works": [
        "https://openalex.org/W1234",
        "https://openalex.org/W5678",
    ],
}


# ============================================================================
# Tests: normalisation
# ============================================================================


class TestNormaliseCrossRef:
    """Tests for CrossRef record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_crossref(CROSSREF_WORK["message"])
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["source"] == "crossref"

    def test_authors_formatted(self):
        record = lit_search._normalise_crossref(CROSSREF_WORK["message"])
        assert record["authors"] == [
            "Cox, Simon J. D.",
            "Gonzalez-Beltran, Alejandra N.",
        ]

    def test_missing_fields_are_none(self):
        record = lit_search._normalise_crossref({})
        assert record["title"] is None
        assert record["year"] is None
        assert record["doi"] is None
        assert record["authors"] == []


class TestNormaliseS2:
    """Tests for Semantic Scholar record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_s2(S2_PAPER)
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["s2_id"] == "7e2451a298b1c5c6dd7c7c881861a8cb3621f6fa"
        assert record["source"] == "s2"

    def test_authors_are_names(self):
        record = lit_search._normalise_s2(S2_PAPER)
        assert "Simon J. D. Cox" in record["authors"]

    def test_missing_external_ids(self):
        paper = {**S2_PAPER, "externalIds": None}
        record = lit_search._normalise_s2(paper)
        assert record["doi"] is None


class TestNormaliseOpenAlex:
    """Tests for OpenAlex record normalisation."""

    def test_basic_fields(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert record["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert record["year"] == 2021
        assert record["doi"] == "10.1371/journal.pcbi.1009041"
        assert record["openalex_id"] == "https://openalex.org/W3113245274"
        assert record["source"] == "openalex"

    def test_doi_prefix_stripped(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert not record["doi"].startswith("https://")

    def test_abstract_reconstructed(self):
        record = lit_search._normalise_openalex(OPENALEX_WORK)
        assert record["abstract"] == "We present ten simple rules"


# ============================================================================
# Tests: deduplication
# ============================================================================


class TestDeduplication:
    """Tests for cross-source deduplication."""

    def test_same_doi_kept_once(self):
        papers = [
            {"doi": "10.1234/test", "title": "Paper A", "source": "crossref",
             "authors": None, "year": None},
            {"doi": "10.1234/test", "title": "Paper A", "source": "s2",
             "authors": ["Author"], "year": 2021},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 1

    def test_prefers_more_complete_record(self):
        papers = [
            {"doi": "10.1234/test", "title": None, "source": "crossref",
             "authors": None, "year": None, "abstract": None},
            {"doi": "10.1234/test", "title": "Full Title", "source": "s2",
             "authors": ["Author"], "year": 2021, "abstract": "Text"},
        ]
        result = lit_search._deduplicate(papers)
        assert result[0]["title"] == "Full Title"

    def test_papers_without_doi_kept(self):
        papers = [
            {"doi": None, "title": "Paper A", "source": "crossref"},
            {"doi": None, "title": "Paper B", "source": "s2"},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 2

    def test_case_insensitive_doi_matching(self):
        papers = [
            {"doi": "10.1234/TEST", "title": "Paper A", "source": "crossref"},
            {"doi": "10.1234/test", "title": "Paper A", "source": "s2"},
        ]
        result = lit_search._deduplicate(papers)
        assert len(result) == 1


# ============================================================================
# Tests: subcommands with mocked HTTP
# ============================================================================


class TestMetadata:
    """Tests for the metadata subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_merges_multiple_sources(self, mock_get):
        """Metadata from multiple sources is merged into one record."""
        mock_get.side_effect = [
            CROSSREF_WORK,        # CrossRef
            S2_PAPER,             # S2
            OPENALEX_WORK,        # OpenAlex
        ]
        client = MagicMock()
        result = lit_search.cmd_metadata("10.1371/journal.pcbi.1009041", client)
        assert result["title"] == "Ten simple rules for making a vocabulary FAIR"
        assert result["s2_id"] is not None
        assert result["openalex_id"] is not None
        assert "crossref" in result["sources"]

    @patch.object(lit_search, "_safe_get")
    def test_handles_all_sources_failing(self, mock_get):
        """Returns error when all sources fail."""
        mock_get.return_value = None
        client = MagicMock()
        result = lit_search.cmd_metadata("10.9999/nonexistent", client)
        assert "error" in result


class TestReferences:
    """Tests for the references (backward chaining) subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_crossref_references_parsed(self, mock_get):
        """CrossRef reference array is correctly parsed."""
        mock_get.side_effect = [
            CROSSREF_WORK,    # CrossRef
            None,             # S2 fails
            None,             # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        # CrossRef fixture has 3 references (one unstructured)
        assert len(result) >= 2
        dois = [p["doi"] for p in result if p.get("doi")]
        assert "10.1038/sdata.2016.18" in dois

    @patch.object(lit_search, "_safe_get")
    def test_crossref_fails_s2_fallback(self, mock_get):
        """Falls back to S2 when CrossRef returns nothing."""
        mock_get.side_effect = [
            {"message": {}},           # CrossRef: no references
            S2_PAPER_WITH_REFS,        # S2: has references
            None,                      # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        assert len(result) >= 1
        # Should have the unique S2 reference
        dois = [p["doi"] for p in result if p.get("doi")]
        assert "10.9999/unique" in dois

    @patch.object(lit_search, "_safe_get")
    def test_deduplicates_across_sources(self, mock_get):
        """Same DOI from CrossRef and S2 appears only once."""
        mock_get.side_effect = [
            CROSSREF_WORK,             # CrossRef: has 10.1038/sdata.2016.18
            S2_PAPER_WITH_REFS,        # S2: also has 10.1038/sdata.2016.18
            None,                      # OpenAlex fails
        ]
        client = MagicMock()
        result = lit_search.cmd_references("10.1371/journal.pcbi.1009041", client)
        fair_refs = [
            p for p in result if p.get("doi") == "10.1038/sdata.2016.18"
        ]
        assert len(fair_refs) == 1


class TestCitations:
    """Tests for the citations (forward chaining) subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_sorted_by_citation_count(self, mock_get):
        """Citations are sorted by citation count descending."""
        mock_get.side_effect = [
            S2_PAPER_WITH_CITATIONS,   # S2
            None,                       # OpenAlex DOI resolve fails
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client
        )
        assert len(result) == 2
        # Citation counts should be descending
        counts = [p.get("citation_count", 0) for p in result]
        assert counts == sorted(counts, reverse=True)

    @patch.object(lit_search, "_safe_get")
    def test_respects_limit(self, mock_get):
        """Limit parameter caps the number of results."""
        mock_get.side_effect = [
            S2_PAPER_WITH_CITATIONS,
            None,
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client, limit=1
        )
        assert len(result) <= 1


# ============================================================================
# Tests: helpers
# ============================================================================


class TestParseYear:
    """Tests for year parsing from various formats."""

    def test_string_year(self):
        assert lit_search._parse_year("2021") == 2021

    def test_int_year(self):
        assert lit_search._parse_year(2021) == 2021

    def test_none_year(self):
        assert lit_search._parse_year(None) is None

    def test_garbage_year(self):
        assert lit_search._parse_year("not-a-year") is None

    def test_date_string(self):
        assert lit_search._parse_year("2021-06-24") == 2021


class TestReconstructAbstract:
    """Tests for OpenAlex inverted index abstract reconstruction."""

    def test_basic_reconstruction(self):
        raw = {
            "abstract_inverted_index": {
                "Hello": [0],
                "world": [1],
                "foo": [2],
            }
        }
        result = lit_search._reconstruct_openalex_abstract(raw)
        assert result == "Hello world foo"

    def test_missing_index(self):
        assert lit_search._reconstruct_openalex_abstract({}) is None

    def test_repeated_words(self):
        raw = {
            "abstract_inverted_index": {
                "the": [0, 2],
                "cat": [1],
                "sat": [3],
            }
        }
        result = lit_search._reconstruct_openalex_abstract(raw)
        assert result == "the cat the sat"


class TestParseYearRangeValidation:
    """Tests for year range validation (audit fix)."""

    def test_nonsensical_small_year(self):
        assert lit_search._parse_year(3) is None

    def test_nonsensical_two_digit(self):
        assert lit_search._parse_year(20) is None

    def test_valid_historical_year(self):
        assert lit_search._parse_year(1850) == 1850

    def test_boundary_low(self):
        assert lit_search._parse_year(1400) == 1400

    def test_boundary_high(self):
        assert lit_search._parse_year(2100) == 2100

    def test_out_of_range_high(self):
        assert lit_search._parse_year(2101) is None


# ============================================================================
# Tests: _safe_get (HTTP layer)
# ============================================================================


class TestSafeGet:
    """Tests for the HTTP request wrapper with rate limiting and retries."""

    def _make_mock_response(
        self, status_code: int = 200, json_data: dict | None = None,
        raise_json_error: bool = False,
    ) -> MagicMock:
        """Create a mock httpx response."""
        mock = MagicMock()
        mock.status_code = status_code
        if raise_json_error:
            mock.json.side_effect = json.JSONDecodeError(
                "test", "doc", 0
            )
        else:
            mock.json.return_value = json_data or {}
        return mock

    @patch.object(lit_search, "_rate_limit")
    def test_success_returns_json(self, mock_rl):
        """200 response with valid dict JSON returns the dict."""
        client = MagicMock()
        expected = {"message": {"title": "Test"}}
        client.get.return_value = self._make_mock_response(
            200, expected
        )
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result == expected

    @patch.object(lit_search, "_rate_limit")
    def test_non_200_returns_none(self, mock_rl):
        """Non-200 status code returns None."""
        client = MagicMock()
        client.get.return_value = self._make_mock_response(404)
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None

    @patch("time.sleep")
    @patch.object(lit_search, "_rate_limit")
    def test_429_retries_once(self, mock_rl, mock_sleep):
        """429 then 200 returns the second response."""
        client = MagicMock()
        expected = {"message": "ok"}
        client.get.side_effect = [
            self._make_mock_response(429),
            self._make_mock_response(200, expected),
        ]
        result = lit_search._safe_get(client, "http://test", "s2")
        assert result == expected
        mock_sleep.assert_called_once_with(5.0)
        # _rate_limit called twice: initial + before retry
        assert mock_rl.call_count == 2

    @patch("time.sleep")
    @patch.object(lit_search, "_rate_limit")
    def test_429_twice_returns_none(self, mock_rl, mock_sleep):
        """429 on both attempts returns None."""
        client = MagicMock()
        client.get.side_effect = [
            self._make_mock_response(429),
            self._make_mock_response(429),
        ]
        result = lit_search._safe_get(client, "http://test", "s2")
        assert result is None

    @patch.object(lit_search, "_rate_limit")
    def test_network_error_returns_none(self, mock_rl):
        """httpx.HTTPError returns None."""
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("Connection refused")
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None

    @patch.object(lit_search, "_rate_limit")
    def test_invalid_json_returns_none(self, mock_rl):
        """Valid HTTP but invalid JSON returns None."""
        client = MagicMock()
        client.get.return_value = self._make_mock_response(
            200, raise_json_error=True
        )
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None

    @patch.object(lit_search, "_rate_limit")
    def test_non_dict_json_returns_none(self, mock_rl):
        """JSON response that is a list (not dict) returns None."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ["not", "a", "dict"]
        client.get.return_value = mock_resp
        result = lit_search._safe_get(client, "http://test", "crossref")
        assert result is None


# ============================================================================
# Tests: cmd_search
# ============================================================================


CROSSREF_SEARCH_RESPONSE = {
    "message": {
        "items": [
            {
                "DOI": "10.1234/paper-a",
                "title": ["Paper A about FAIR"],
                "author": [{"given": "Alice", "family": "Smith"}],
                "published-print": {"date-parts": [[2021]]},
                "is-referenced-by-count": 10,
            },
            {
                "DOI": "10.1234/paper-b",
                "title": ["Paper B about SKOS"],
                "author": [{"given": "Bob", "family": "Jones"}],
                "published-print": {"date-parts": [[2022]]},
                "is-referenced-by-count": 5,
            },
        ]
    }
}


OPENALEX_SEARCH_RESPONSE = {
    "results": [
        {
            "id": "https://openalex.org/W999",
            "doi": "https://doi.org/10.1234/paper-a",
            "display_name": "Paper A about FAIR",
            "publication_year": 2021,
            "cited_by_count": 12,
            "authorships": [
                {"author": {"display_name": "Alice Smith"}}
            ],
        },
        {
            "id": "https://openalex.org/W888",
            "doi": "https://doi.org/10.5678/paper-c",
            "display_name": "Paper C unique to OpenAlex",
            "publication_year": 2023,
            "cited_by_count": 3,
            "authorships": [
                {"author": {"display_name": "Carol Lee"}}
            ],
        },
    ]
}


class TestSearch:
    """Tests for the search subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_crossref_and_openalex_merged(self, mock_get):
        """Results from both sources are merged and deduplicated."""
        mock_get.side_effect = [
            CROSSREF_SEARCH_RESPONSE,
            OPENALEX_SEARCH_RESPONSE,
        ]
        client = MagicMock()
        result = lit_search.cmd_search("FAIR vocabulary", client)
        # Paper A appears in both — should be deduped
        # Papers B and C are unique → 3 total
        assert len(result) == 3
        dois = [p.get("doi") for p in result if p.get("doi")]
        assert "10.1234/paper-a" in dois
        assert "10.1234/paper-b" in dois
        assert "10.5678/paper-c" in dois

    @patch.object(lit_search, "_safe_get")
    def test_respects_limit_after_dedup(self, mock_get):
        """Limit is enforced after deduplication."""
        mock_get.side_effect = [
            CROSSREF_SEARCH_RESPONSE,     # 2 papers
            OPENALEX_SEARCH_RESPONSE,     # 1 unique + 1 dup = 3 total
        ]
        client = MagicMock()
        result = lit_search.cmd_search("FAIR", client, limit=2)
        assert len(result) <= 2


# ============================================================================
# Tests: cmd_openalex_cited_by
# ============================================================================


OPENALEX_RESOLVE_RESPONSE = {
    "id": "https://openalex.org/W3113245274",
    "cited_by_count": 40,
}


OPENALEX_CITED_BY_RESPONSE = {
    "results": [
        {
            "id": "https://openalex.org/W111",
            "doi": "https://doi.org/10.9999/citer-1",
            "display_name": "Paper that cites target",
            "publication_year": 2023,
            "cited_by_count": 25,
            "authorships": [
                {"author": {"display_name": "Dan Brown"}}
            ],
        },
    ]
}


class TestOpenAlexCitedBy:
    """Tests for the openalex-cited-by subcommand."""

    @patch.object(lit_search, "_safe_get")
    def test_returns_citing_papers(self, mock_get):
        """DOI resolves and citing papers are returned."""
        mock_get.side_effect = [
            OPENALEX_RESOLVE_RESPONSE,
            OPENALEX_CITED_BY_RESPONSE,
        ]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client
        )
        assert len(result) == 1
        assert result[0]["doi"] == "10.9999/citer-1"

    @patch.object(lit_search, "_safe_get")
    def test_doi_not_found_returns_empty(self, mock_get):
        """DOI resolution fails → empty list."""
        mock_get.return_value = None
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.9999/nonexistent", client
        )
        assert result == []

    @patch.object(lit_search, "_safe_get")
    def test_no_citations_returns_empty(self, mock_get):
        """DOI resolves but no citing papers → empty list."""
        mock_get.side_effect = [
            OPENALEX_RESOLVE_RESPONSE,
            {"results": []},
        ]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client
        )
        assert result == []
