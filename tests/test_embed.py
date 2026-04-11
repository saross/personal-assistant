"""Tests for scripts/embed.py — Ollama embedding client."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import embed


# ============================================================================
# Tests — build_embed_text
# ============================================================================


class TestBuildEmbedText:
    """Tests for text construction from memory records."""

    def test_full_record(self) -> None:
        """Should concatenate content, summary, and source_context."""
        record = {
            "content": "Decision to use pgvector for semantic search.",
            "summary": "Chose pgvector over alternatives.",
            "source_context": "Architecture discussion",
        }
        result = embed.build_embed_text(record)
        assert "pgvector" in result
        assert "alternatives" in result
        assert "Architecture" in result

    def test_missing_summary(self) -> None:
        """Should handle missing summary gracefully."""
        record = {"content": "Some content here."}
        result = embed.build_embed_text(record)
        assert result == "Some content here."

    def test_none_fields(self) -> None:
        """Should handle None values in optional fields."""
        record = {
            "content": "Core content.",
            "summary": None,
            "source_context": None,
        }
        result = embed.build_embed_text(record)
        assert result == "Core content."

    def test_empty_content(self) -> None:
        """Should return empty string for empty record."""
        record = {"content": ""}
        result = embed.build_embed_text(record)
        assert result == ""

    def test_empty_record(self) -> None:
        """Should handle completely empty record."""
        result = embed.build_embed_text({})
        assert result == ""


# ============================================================================
# Tests — is_ollama_available
# ============================================================================


class TestIsOllamaAvailable:
    """Tests for Ollama health check."""

    def test_model_present(self) -> None:
        """Should return True when model is in the tags list."""
        mock_response = json.dumps({
            "models": [
                {"name": "nomic-embed-text:latest"},
                {"name": "gemma4:e4b-it-q8_0"},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("embed.urllib.request.urlopen", return_value=mock_resp):
            assert embed.is_ollama_available("nomic-embed-text") is True

    def test_model_absent(self) -> None:
        """Should return False when model is not in tags."""
        mock_response = json.dumps({
            "models": [{"name": "gemma4:e4b-it-q8_0"}]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("embed.urllib.request.urlopen", return_value=mock_resp):
            assert embed.is_ollama_available("nomic-embed-text") is False

    def test_connection_error(self) -> None:
        """Should return False when Ollama is not running."""
        import urllib.error

        with patch(
            "embed.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            assert embed.is_ollama_available() is False


# ============================================================================
# Tests — generate_embeddings
# ============================================================================


class TestGenerateEmbeddings:
    """Tests for batch embedding generation."""

    def test_successful_batch(self) -> None:
        """Should return embeddings for all inputs."""
        mock_response = json.dumps({
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("embed.urllib.request.urlopen", return_value=mock_resp):
            result = embed.generate_embeddings(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    def test_connection_error(self) -> None:
        """Should return list of None on connection failure."""
        import urllib.error

        with patch(
            "embed.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = embed.generate_embeddings(["text1", "text2"])

        assert len(result) == 2
        assert result[0] is None
        assert result[1] is None

    def test_timeout(self) -> None:
        """Should return list of None on timeout."""
        with patch(
            "embed.urllib.request.urlopen",
            side_effect=TimeoutError("Timed out"),
        ):
            result = embed.generate_embeddings(["text1"])

        assert len(result) == 1
        assert result[0] is None

    def test_empty_input(self) -> None:
        """Should return empty list for empty input."""
        result = embed.generate_embeddings([])
        assert result == []

    def test_fewer_embeddings_than_inputs(self) -> None:
        """Should pad with None if server returns too few embeddings."""
        mock_response = json.dumps({
            "embeddings": [[0.1, 0.2]]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("embed.urllib.request.urlopen", return_value=mock_resp):
            result = embed.generate_embeddings(["text1", "text2", "text3"])

        assert len(result) == 3
        assert result[0] == [0.1, 0.2]
        assert result[1] is None
        assert result[2] is None


# ============================================================================
# Tests — embed_single
# ============================================================================


class TestEmbedSingle:
    """Tests for single-text embedding convenience wrapper."""

    def test_returns_vector(self) -> None:
        """Should return a single vector."""
        mock_response = json.dumps({
            "embeddings": [[0.1, 0.2, 0.3]]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("embed.urllib.request.urlopen", return_value=mock_resp):
            result = embed.embed_single("test text")

        assert result == [0.1, 0.2, 0.3]

    def test_returns_none_on_failure(self) -> None:
        """Should return None when embedding fails."""
        import urllib.error

        with patch(
            "embed.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = embed.embed_single("test text")

        assert result is None
