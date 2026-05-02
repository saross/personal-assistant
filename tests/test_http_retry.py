"""
Tests for scripts/_http_retry.py — shared HTTP retry helper (audit IC7).

Covers:

* Pure helpers: ``parse_retry_after``, ``compute_backoff``,
  ``is_transient_status``.
* ``urlopen_with_retry``: retry on transient HTTP errors, retry on
  network errors, ``Retry-After`` honour, terminal-4xx propagation,
  exhaustion behaviour.

Time and randomness are mocked so the tests are deterministic and fast.
"""

from __future__ import annotations

import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _http_retry  # noqa: E402


# ---------------------------------------------------------------------------
# parse_retry_after
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Honour the ``Retry-After`` header in seconds form."""

    def test_none_returns_none(self) -> None:
        assert _http_retry.parse_retry_after(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _http_retry.parse_retry_after("") is None
        assert _http_retry.parse_retry_after("   ") is None

    def test_integer_seconds(self) -> None:
        assert _http_retry.parse_retry_after("3") == 3.0

    def test_float_seconds(self) -> None:
        assert _http_retry.parse_retry_after("2.5") == 2.5

    def test_clamped_to_max(self) -> None:
        # 86400 (a day) clamps to RETRY_AFTER_MAX_S so a misbehaving
        # server cannot stall a cron tick.
        assert (
            _http_retry.parse_retry_after("86400")
            == _http_retry.RETRY_AFTER_MAX_S
        )

    def test_clamped_to_min(self) -> None:
        # A zero or sub-second value is rounded up to the minimum so the
        # caller always actually waits.
        assert (
            _http_retry.parse_retry_after("0")
            == _http_retry.RETRY_AFTER_MIN_S
        )

    def test_negative_returns_none(self) -> None:
        assert _http_retry.parse_retry_after("-1") is None

    def test_http_date_returns_none(self) -> None:
        # We deliberately do not parse the HTTP-date form; caller falls
        # back to its own backoff.
        assert (
            _http_retry.parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT")
            is None
        )

    def test_garbage_returns_none(self) -> None:
        assert _http_retry.parse_retry_after("not-a-number") is None


# ---------------------------------------------------------------------------
# compute_backoff
# ---------------------------------------------------------------------------


class TestComputeBackoff:
    """Exponential backoff with jitter."""

    def test_exponential_no_jitter(self) -> None:
        assert _http_retry.compute_backoff(1, base_backoff=1.0, jitter=False) == 1.0
        assert _http_retry.compute_backoff(2, base_backoff=1.0, jitter=False) == 2.0
        assert _http_retry.compute_backoff(3, base_backoff=1.0, jitter=False) == 4.0

    def test_base_backoff_scales(self) -> None:
        assert _http_retry.compute_backoff(1, base_backoff=0.5, jitter=False) == 0.5
        assert _http_retry.compute_backoff(2, base_backoff=0.5, jitter=False) == 1.0
        assert _http_retry.compute_backoff(3, base_backoff=2.0, jitter=False) == 8.0

    def test_jitter_adds_at_most_half_base(self) -> None:
        # With base=1.0, jitter is in [0, 0.5). Worst case attempt 1 = 1.0 + 0.5.
        with patch("_http_retry.random.random", return_value=0.999_999):
            delay = _http_retry.compute_backoff(1, base_backoff=1.0, jitter=True)
        assert 1.0 <= delay < 1.5

    def test_jitter_zero_when_random_is_zero(self) -> None:
        with patch("_http_retry.random.random", return_value=0.0):
            delay = _http_retry.compute_backoff(1, base_backoff=1.0, jitter=True)
        assert delay == 1.0

    def test_attempt_below_one_is_treated_as_one(self) -> None:
        assert _http_retry.compute_backoff(0, base_backoff=1.0, jitter=False) == 1.0
        assert _http_retry.compute_backoff(-5, base_backoff=1.0, jitter=False) == 1.0


# ---------------------------------------------------------------------------
# is_transient_status
# ---------------------------------------------------------------------------


class TestIsTransientStatus:
    """Default transient status set."""

    def test_default_set(self) -> None:
        for code in (408, 429, 500, 502, 503, 504):
            assert _http_retry.is_transient_status(code) is True

    def test_terminal_codes(self) -> None:
        for code in (200, 301, 400, 401, 403, 404, 410):
            assert _http_retry.is_transient_status(code) is False

    def test_custom_set(self) -> None:
        assert _http_retry.is_transient_status(418, transient_status=(418,)) is True
        assert _http_retry.is_transient_status(429, transient_status=(418,)) is False


# ---------------------------------------------------------------------------
# urlopen_with_retry
# ---------------------------------------------------------------------------


def _make_http_error(
    code: int,
    *,
    retry_after: str | None = None,
) -> urllib.error.HTTPError:
    """Construct an HTTPError with optional Retry-After header."""
    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    # email.message.Message-like behaviour for ``.get`` is what HTTPError
    # exposes via ``.headers``; a plain dict satisfies the access we need.
    msg = MagicMock()
    msg.get = lambda key, default=None: headers.get(key, default)
    return urllib.error.HTTPError(
        "http://example/", code, "transient", msg, BytesIO(b""),
    )


class TestUrlopenWithRetry:
    """Cover the retry control-flow paths."""

    def test_success_first_try(self) -> None:
        """Returns immediately when urlopen succeeds."""
        sentinel = MagicMock(name="response")
        with patch("_http_retry.urllib.request.urlopen", return_value=sentinel) as m:
            req = MagicMock(name="request")
            result = _http_retry.urlopen_with_retry(req, max_attempts=3)
        assert result is sentinel
        assert m.call_count == 1

    def test_terminal_4xx_does_not_retry(self) -> None:
        """A 404 propagates immediately without retry."""
        terminal = _make_http_error(404)
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=terminal,
        ) as m, patch("_http_retry.time.sleep") as sleep_mock:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                _http_retry.urlopen_with_retry(MagicMock(), max_attempts=3)
        assert exc_info.value.code == 404
        assert m.call_count == 1
        sleep_mock.assert_not_called()

    def test_transient_5xx_retries_then_succeeds(self) -> None:
        """A 503 followed by a 200 returns the 200."""
        sentinel = MagicMock(name="response")
        side_effects = [_make_http_error(503), sentinel]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ) as m, patch("_http_retry.time.sleep") as sleep_mock, patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            result = _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=3, base_backoff=1.0,
            )
        assert result is sentinel
        assert m.call_count == 2
        # base_backoff=1.0, attempt=1, no jitter → exactly 1.0s
        sleep_mock.assert_called_once_with(1.0)

    def test_429_retry_after_honoured(self) -> None:
        """A 429 with Retry-After: 7 sleeps for 7 s, not the computed backoff."""
        sentinel = MagicMock(name="response")
        side_effects = [_make_http_error(429, retry_after="7"), sentinel]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ), patch("_http_retry.time.sleep") as sleep_mock:
            result = _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=2, base_backoff=1.0,
            )
        assert result is sentinel
        sleep_mock.assert_called_once_with(7.0)

    def test_429_without_retry_after_uses_backoff(self) -> None:
        """A 429 with no header falls back to compute_backoff."""
        sentinel = MagicMock(name="response")
        side_effects = [_make_http_error(429), sentinel]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ), patch("_http_retry.time.sleep") as sleep_mock, patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=2, base_backoff=1.0,
            )
        sleep_mock.assert_called_once_with(1.0)

    def test_429_can_disable_retry_after(self) -> None:
        """``honour_retry_after=False`` ignores the header."""
        sentinel = MagicMock(name="response")
        side_effects = [_make_http_error(429, retry_after="7"), sentinel]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ), patch("_http_retry.time.sleep") as sleep_mock, patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            _http_retry.urlopen_with_retry(
                MagicMock(),
                max_attempts=2,
                base_backoff=1.0,
                honour_retry_after=False,
            )
        sleep_mock.assert_called_once_with(1.0)

    def test_network_error_retries(self) -> None:
        """A URLError followed by success returns the success."""
        sentinel = MagicMock(name="response")
        side_effects = [
            urllib.error.URLError("Connection refused"),
            sentinel,
        ]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ) as m, patch("_http_retry.time.sleep") as sleep_mock, patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            result = _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=3, base_backoff=1.0,
            )
        assert result is sentinel
        assert m.call_count == 2
        sleep_mock.assert_called_once_with(1.0)

    def test_timeout_retries(self) -> None:
        """A TimeoutError followed by success returns the success."""
        sentinel = MagicMock(name="response")
        side_effects = [TimeoutError("read timed out"), sentinel]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ), patch("_http_retry.time.sleep"), patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            result = _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=3, base_backoff=1.0,
            )
        assert result is sentinel

    def test_exhausted_retries_raises(self) -> None:
        """All attempts fail — final exception propagates."""
        side_effects = [_make_http_error(503), _make_http_error(503), _make_http_error(503)]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ) as m, patch("_http_retry.time.sleep"), patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                _http_retry.urlopen_with_retry(
                    MagicMock(), max_attempts=3, base_backoff=1.0,
                )
        assert exc_info.value.code == 503
        assert m.call_count == 3

    def test_exponential_growth_between_retries(self) -> None:
        """Attempt 2 waits 2.0 s, attempt 3 waits 4.0 s (no jitter)."""
        sentinel = MagicMock(name="response")
        side_effects = [
            _make_http_error(503),
            _make_http_error(503),
            sentinel,
        ]
        with patch(
            "_http_retry.urllib.request.urlopen", side_effect=side_effects,
        ), patch("_http_retry.time.sleep") as sleep_mock, patch(
            "_http_retry.random.random", return_value=0.0,
        ):
            _http_retry.urlopen_with_retry(
                MagicMock(), max_attempts=3, base_backoff=1.0,
            )
        # Two sleeps before the successful third attempt: 1.0 then 2.0.
        assert sleep_mock.call_count == 2
        assert sleep_mock.call_args_list[0].args == (1.0,)
        assert sleep_mock.call_args_list[1].args == (2.0,)

    def test_max_attempts_one_does_not_retry(self) -> None:
        """``max_attempts=1`` raises on the first failure with no sleep."""
        with patch(
            "_http_retry.urllib.request.urlopen",
            side_effect=_make_http_error(503),
        ), patch("_http_retry.time.sleep") as sleep_mock:
            with pytest.raises(urllib.error.HTTPError):
                _http_retry.urlopen_with_retry(
                    MagicMock(), max_attempts=1,
                )
        sleep_mock.assert_not_called()
