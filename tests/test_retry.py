from unittest.mock import MagicMock

import deezer.exceptions
import httpx
import pytest
import spotipy

from SyncZik.retry import with_retry


def _deezer_http_error(status_code: int, text: str = '{"error": "boom"}') -> deezer.exceptions.DeezerHTTPError:
    request = httpx.Request("GET", "https://api.deezer.com/x")
    response = httpx.Response(status_code, request=request, text=text)
    http_exc = httpx.HTTPStatusError("error", request=request, response=response)
    return deezer.exceptions.DeezerHTTPError.from_http_error(http_exc)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("SyncZik.retry.time.sleep", lambda seconds: None)


class TestWithRetry:
    def test_returns_result_on_first_success(self):
        fn = MagicMock(return_value="ok")
        assert with_retry(fn) == "ok"
        assert fn.call_count == 1

    def test_retries_spotify_429_then_succeeds(self):
        fn = MagicMock(side_effect=[
            spotipy.SpotifyException(429, -1, "rate limited", headers={"Retry-After": "0"}),
            "ok",
        ])
        assert with_retry(fn, max_attempts=3) == "ok"
        assert fn.call_count == 2

    def test_gives_up_after_max_attempts(self):
        exc = spotipy.SpotifyException(429, -1, "rate limited")
        fn = MagicMock(side_effect=[exc, exc, exc])
        with pytest.raises(spotipy.SpotifyException):
            with_retry(fn, max_attempts=3)
        assert fn.call_count == 3

    def test_does_not_retry_non_transient_spotify_error(self):
        fn = MagicMock(side_effect=spotipy.SpotifyException(404, -1, "not found"))
        with pytest.raises(spotipy.SpotifyException):
            with_retry(fn, max_attempts=3)
        assert fn.call_count == 1

    def test_respects_retry_after_header(self, monkeypatch):
        sleep_calls = []
        monkeypatch.setattr("SyncZik.retry.time.sleep", lambda seconds: sleep_calls.append(seconds))

        fn = MagicMock(side_effect=[
            spotipy.SpotifyException(429, -1, "rate limited", headers={"Retry-After": "5"}),
            "ok",
        ])
        with_retry(fn)
        assert sleep_calls == [5.0]

    def test_retries_deezer_retryable_http_error(self):
        fn = MagicMock(side_effect=[_deezer_http_error(503), "ok"])
        assert with_retry(fn) == "ok"
        assert fn.call_count == 2

    def test_retries_deezer_429_generic_http_error(self):
        fn = MagicMock(side_effect=[_deezer_http_error(429), "ok"])
        assert with_retry(fn) == "ok"
        assert fn.call_count == 2

    def test_does_not_retry_deezer_404(self):
        fn = MagicMock(side_effect=_deezer_http_error(404))
        with pytest.raises(deezer.exceptions.DeezerHTTPError):
            with_retry(fn, max_attempts=3)
        assert fn.call_count == 1

    def test_does_not_retry_deezer_403(self):
        fn = MagicMock(side_effect=_deezer_http_error(403))
        with pytest.raises(deezer.exceptions.DeezerHTTPError):
            with_retry(fn, max_attempts=3)
        assert fn.call_count == 1

    def test_retries_network_timeout(self):
        fn = MagicMock(side_effect=[httpx.TimeoutException("timeout"), "ok"])
        assert with_retry(fn) == "ok"
        assert fn.call_count == 2

    def test_retries_connect_error(self):
        fn = MagicMock(side_effect=[httpx.ConnectError("refused"), "ok"])
        assert with_retry(fn) == "ok"
        assert fn.call_count == 2

    def test_does_not_retry_unrecognized_exception(self):
        fn = MagicMock(side_effect=ValueError("bug"))
        with pytest.raises(ValueError):
            with_retry(fn, max_attempts=3)
        assert fn.call_count == 1
