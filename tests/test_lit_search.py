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


# ============================================================================
# Tests: cmd_bibtex
# ============================================================================


SAMPLE_BIBTEX = (
    "@article{Walters_2023, title={Fabrication and errors in the "
    "bibliographic citations generated by ChatGPT}, author={Walters, "
    "William H. and Wilder, Esther Isabelle}, year={2023} }"
)


class TestBibtex:
    """Tests for the bibtex subcommand."""

    @patch.object(lit_search, "_rate_limit")
    def test_single_doi_returns_entry(self, mock_rl):
        """Single DOI returns its BibTeX entry."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_BIBTEX
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(
            ["10.1038/s41598-023-41032-5"], client
        )
        assert "Walters_2023" in result
        assert "Fabrication and errors" in result

    @patch.object(lit_search, "_rate_limit")
    def test_multiple_dois_concatenated(self, mock_rl):
        """Multiple DOIs return concatenated entries."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_BIBTEX
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(
            ["10.1/a", "10.1/b", "10.1/c"], client
        )
        assert result.count("Walters_2023") == 3
        assert client.get.call_count == 3

    @patch.object(lit_search, "_rate_limit")
    def test_failed_doi_leaves_comment(self, mock_rl):
        """A 404 response leaves a comment marker, not blank."""
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client.get.return_value = mock_resp

        result = lit_search.cmd_bibtex(["10.9999/nonexistent"], client)
        assert "FAILED" in result
        assert "10.9999/nonexistent" in result

    @patch.object(lit_search, "_rate_limit")
    def test_mixed_success_and_failure(self, mock_rl):
        """One DOI succeeds, one fails — both represented in output."""
        client = MagicMock()
        good_resp = MagicMock()
        good_resp.status_code = 200
        good_resp.text = SAMPLE_BIBTEX
        bad_resp = MagicMock()
        bad_resp.status_code = 404
        client.get.side_effect = [good_resp, bad_resp]

        result = lit_search.cmd_bibtex(
            ["10.1/good", "10.1/bad"], client
        )
        assert "Walters_2023" in result
        assert "FAILED" in result

    @patch.object(lit_search, "_rate_limit")
    def test_network_error_leaves_comment(self, mock_rl):
        """httpx network error leaves a comment marker."""
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("refused")

        result = lit_search.cmd_bibtex(["10.9999/oops"], client)
        assert "FAILED" in result
        assert "10.9999/oops" in result


# ============================================================================
# Tests: Batch 9 — Cluster D pagination correctness (D-M4, D-M5, D-M6)
# ============================================================================


def _openalex_page(results, next_cursor):
    """Build an OpenAlex-shaped response page for pagination tests."""
    return {
        "results": results,
        "meta": {"next_cursor": next_cursor},
    }


def _openalex_work(idx: int, citations: int = 0) -> dict:
    """Synthesise a minimal OpenAlex work record for pagination tests."""
    return {
        "id": f"https://openalex.org/W{idx:06d}",
        "doi": f"https://doi.org/10.9999/page-{idx}",
        "display_name": f"Paper {idx}",
        "publication_year": 2024,
        "cited_by_count": citations,
        "authorships": [
            {"author": {"display_name": f"Author {idx}"}}
        ],
    }


class TestOpenAlexCursorPagination:
    """
    D-M6 pin: OpenAlex cursor pagination must use the API's documented
    `cursor=*` opaque-token mechanism, not page-number / offset paging,
    and must follow `meta.next_cursor` until exhausted or `limit` met.
    """

    @patch.object(lit_search, "_safe_get")
    def test_initial_request_uses_star_cursor(self, mock_get):
        """First request sets cursor=* — the OpenAlex initial token."""
        mock_get.return_value = _openalex_page(
            [_openalex_work(1)], next_cursor=None,
        )
        client = MagicMock()
        lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=5,
        )
        # Inspect the params actually passed
        first_call_kwargs = mock_get.call_args_list[0].kwargs
        params = first_call_kwargs["params"]
        assert params["cursor"] == "*"
        # And we should NOT be using `page=` offset paging.
        assert "page" not in params

    @patch.object(lit_search, "_safe_get")
    def test_follows_next_cursor_to_completion(self, mock_get):
        """The helper follows meta.next_cursor across multiple pages."""
        mock_get.side_effect = [
            _openalex_page(
                [_openalex_work(i) for i in range(3)],
                next_cursor="cursor-page-2",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(3, 6)],
                next_cursor="cursor-page-3",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(6, 8)],
                next_cursor=None,
            ),
        ]
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=100,
        )
        assert len(results) == 8
        # Subsequent requests pass the cursor returned by the previous
        # page — proving cursor-token threading.
        cursors_used = [
            call.kwargs["params"]["cursor"]
            for call in mock_get.call_args_list
        ]
        assert cursors_used == ["*", "cursor-page-2", "cursor-page-3"]

    @patch.object(lit_search, "_safe_get")
    def test_limit_caps_total_results(self, mock_get):
        """The helper stops once `limit` results have been collected."""
        # Each page returns 50 records and a cursor; we ask for 75.
        mock_get.side_effect = [
            _openalex_page(
                [_openalex_work(i) for i in range(50)],
                next_cursor="page-2",
            ),
            _openalex_page(
                [_openalex_work(i) for i in range(50, 100)],
                next_cursor="page-3",
            ),
        ]
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=75,
        )
        assert len(results) == 75

    @patch.object(lit_search, "_safe_get")
    def test_stops_on_repeated_cursor(self, mock_get):
        """A misbehaving API echoing the same cursor must not infinite-loop."""
        # API returns the same cursor over and over with one record each.
        mock_get.side_effect = [
            _openalex_page([_openalex_work(0)], next_cursor="stuck"),
            _openalex_page([_openalex_work(1)], next_cursor="stuck"),
            _openalex_page([_openalex_work(2)], next_cursor="stuck"),
        ]
        client = MagicMock()
        # The helper deduplicates seen cursors, so the second time it
        # encounters "stuck" it stops.
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=100,
        )
        # First page (cursor=*) yields 1 record; second page
        # (cursor=stuck) yields another, then we refuse to chase
        # "stuck" again. So at most 2 records.
        assert len(results) <= 2

    @patch.object(lit_search, "_safe_get")
    def test_per_page_never_exceeds_api_max(self, mock_get):
        """`per_page` must never exceed OPENALEX_PER_PAGE_MAX (200)."""
        mock_get.return_value = _openalex_page(
            [_openalex_work(i) for i in range(200)],
            next_cursor=None,
        )
        client = MagicMock()
        lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=10_000,
        )
        for call in mock_get.call_args_list:
            params = call.kwargs["params"]
            assert int(params["per_page"]) <= lit_search.OPENALEX_PER_PAGE_MAX

    @patch.object(lit_search, "_safe_get")
    def test_safe_get_failure_terminates(self, mock_get):
        """A `None` return from `_safe_get` stops the loop cleanly."""
        mock_get.return_value = None
        client = MagicMock()
        results = lit_search._openalex_paginate(
            client, "http://test/works", {"filter": "x"}, limit=50,
        )
        assert results == []


class TestCitationsLimitHonoured:
    """
    D-M6 pin: cmd_citations must return more than 50 results when the
    user asks for more and the API has them.
    """

    @patch.object(lit_search, "_safe_get")
    def test_citations_returns_more_than_50_when_requested(self, mock_get):
        """`--limit 100` returns ~100 results, not silently capped at 50."""
        # First call: S2 paper (no citations envelope to keep it simple)
        # Second call: OpenAlex DOI resolve
        # Subsequent calls: paginated `_safe_get` for the cursor walk
        s2_response = {**S2_PAPER, "citations": []}
        oa_resolve = {"id": "https://openalex.org/W123"}
        # Two pages of 50 OpenAlex citing papers → 100 records total.
        page_1 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50)],
            next_cursor="page-2",
        )
        page_2 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50, 100)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            s2_response,
            oa_resolve,
            page_1,
            page_2,
        ]
        client = MagicMock()
        result = lit_search.cmd_citations(
            "10.1371/journal.pcbi.1009041", client, limit=100,
        )
        # Each OpenAlex paper has a unique DOI so no dedup collapse.
        assert len(result) == 100


class TestOpenAlexCitedByLimitHonoured:
    """
    D-M6 pin: cmd_openalex_cited_by must paginate beyond the first 50.
    """

    @patch.object(lit_search, "_safe_get")
    def test_returns_more_than_50_when_requested(self, mock_get):
        """`--limit 75` returns 75 papers, not 50."""
        oa_resolve = {
            "id": "https://openalex.org/W123",
            "cited_by_count": 200,
        }
        page_1 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50)],
            next_cursor="page-2",
        )
        page_2 = _openalex_page(
            [_openalex_work(i, citations=100 - i) for i in range(50, 100)],
            next_cursor="page-3",
        )
        mock_get.side_effect = [oa_resolve, page_1, page_2]
        client = MagicMock()
        result = lit_search.cmd_openalex_cited_by(
            "10.1371/journal.pcbi.1009041", client, limit=75,
        )
        assert len(result) == 75


class TestReferencesLimitHonoured:
    """
    D-M5 pin: cmd_references' OpenAlex contribution must respect the
    user's `--limit`, not silently truncate at DEFAULT_CITATION_LIMIT (50).
    """

    @patch.object(lit_search, "_safe_get")
    def test_openalex_contribution_uses_limit_not_default(self, mock_get):
        """When --limit=100, OpenAlex resolves up to 100 referenced_works."""
        # 1) CrossRef returns no useful refs
        # 2) S2 returns no refs
        # 3) OpenAlex DOI resolve returns 100 referenced_works
        # 4) The paginated batch resolves them all
        crossref_empty = {"message": {}}
        s2_empty = {"references": []}
        oa_resolve = {
            "referenced_works": [
                f"https://openalex.org/W{i:06d}" for i in range(100)
            ],
        }
        page_1 = _openalex_page(
            [_openalex_work(i) for i in range(100)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            crossref_empty,
            s2_empty,
            oa_resolve,
            page_1,
        ]
        client = MagicMock()
        result = lit_search.cmd_references(
            "10.1371/journal.pcbi.1009041", client, limit=100,
        )
        # Each OpenAlex work has a unique DOI; no dedup loss.
        assert len(result) == 100

    @patch.object(lit_search, "_safe_get")
    def test_openalex_truncates_to_limit_not_default(self, mock_get):
        """
        Inverse of the bug: when `referenced_works` has 200 entries and
        the user asks for `--limit 30`, OpenAlex should request only 30,
        not the old hard-coded 50.
        """
        crossref_empty = {"message": {}}
        s2_empty = {"references": []}
        oa_resolve = {
            "referenced_works": [
                f"https://openalex.org/W{i:06d}" for i in range(200)
            ],
        }
        page_1 = _openalex_page(
            [_openalex_work(i) for i in range(30)],
            next_cursor=None,
        )
        mock_get.side_effect = [
            crossref_empty, s2_empty, oa_resolve, page_1,
        ]
        client = MagicMock()
        result = lit_search.cmd_references(
            "10.1371/journal.pcbi.1009041", client, limit=30,
        )
        assert len(result) <= 30
        # Final result is capped at limit — pin the cap.
        # And we should not have asked OpenAlex to resolve more than 30
        # IDs; inspect the filter parameter on the paginated call.
        # Calls: CrossRef(0), S2(1), OpenAlex resolve(2), paginate page(3).
        paginate_call_params = mock_get.call_args_list[3].kwargs["params"]
        id_filter = paginate_call_params["filter"]
        # The filter is "openalex:id1|id2|..." — count the ids.
        ids_passed = id_filter.split(":", 1)[1].split("|")
        assert len(ids_passed) <= 30


class TestDedupeMergesAcrossPageBoundaries:
    """
    D-M4 pin: when the same record appears across two paginated pages
    (e.g., concurrent edits or sort-tie reorderings), `_deduplicate`
    must merge complementary fields, not emit two records.
    """

    def test_complementary_fields_are_merged_not_dropped(self):
        """
        CrossRef record on page 1 has DOI+year+title but no abstract;
        OpenAlex record on page 2 has DOI+abstract+citation_count but
        no year. The merged record retains both year and abstract.
        """
        page_one_record = {
            "doi": "10.1234/dup",
            "title": "Paper",
            "year": 2021,
            "authors": ["Smith"],
            "abstract": None,
            "citation_count": None,
            "source": "crossref",
        }
        page_two_record = {
            "doi": "10.1234/dup",
            "title": "Paper",
            "year": None,
            "authors": [],
            "abstract": "Long-form abstract text.",
            "citation_count": 42,
            "source": "openalex",
        }
        merged = lit_search._deduplicate(
            [page_one_record, page_two_record]
        )
        assert len(merged) == 1
        record = merged[0]
        assert record["year"] == 2021
        assert record["abstract"] == "Long-form abstract text."
        assert record["citation_count"] == 42

    def test_record_emitted_once_not_twice(self):
        """Two API responses for the same DOI collapse to one record."""
        page_one = [
            {"doi": "10.1234/a", "title": "A", "source": "crossref"},
            {"doi": "10.1234/b", "title": "B", "source": "crossref"},
        ]
        page_two = [
            # 'a' reappears on page 2 (e.g., concurrent edit shifts pos)
            {"doi": "10.1234/a", "title": "A", "source": "openalex"},
            {"doi": "10.1234/c", "title": "C", "source": "openalex"},
        ]
        result = lit_search._deduplicate(page_one + page_two)
        dois = sorted([p["doi"] for p in result])
        assert dois == ["10.1234/a", "10.1234/b", "10.1234/c"]
        # And the merged 'a' record carries both contributing sources.
        a_record = next(p for p in result if p["doi"] == "10.1234/a")
        sources = a_record.get("sources") or []
        assert "crossref" in sources
        assert "openalex" in sources

    def test_merge_preserves_when_one_record_has_extra_field(self):
        """
        Field present on only one record survives the merge — this is
        the heart of D-M4: complementary fields no longer dropped.
        """
        record_a = {
            "doi": "10.1234/x",
            "title": "X",
            "s2_id": "S2-XYZ",
            "abstract": None,
            "source": "s2",
        }
        record_b = {
            "doi": "10.1234/x",
            "title": "X",
            "abstract": "Abstract from CrossRef",
            "source": "crossref",
        }
        merged = lit_search._deduplicate([record_a, record_b])
        assert len(merged) == 1
        assert merged[0]["s2_id"] == "S2-XYZ"
        assert merged[0]["abstract"] == "Abstract from CrossRef"
