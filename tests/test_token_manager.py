"""Tests for TokenManager — token lifecycle, expiry, refresh."""

from unittest.mock import patch

from api_to_tools.auth import TokenManager
from api_to_tools.types import AuthConfig


def _oauth2_auth(**overrides) -> AuthConfig:
    defaults = dict(
        type="oauth2_client",
        token_url="https://auth.example.com/token",
        client_id="test-id",
        client_secret="test-secret",
        scope="read",
    )
    defaults.update(overrides)
    return AuthConfig(**defaults)


def _mock_token_response(access_token="tok_123", expires_in=3600, refresh_token=None):
    return {
        "access_token": access_token,
        "expires_in": expires_in,
        "refresh_token": refresh_token,
    }


# ──────────────────────────────────────────────
# Basic token fetch
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
def test_get_token_fetches_on_first_call(mock_obtain):
    mock_obtain.return_value = _mock_token_response("tok_abc", 3600)
    auth = _oauth2_auth()
    mgr = TokenManager(auth)

    token = mgr.get_token()
    assert token == "tok_abc"
    mock_obtain.assert_called_once()


@patch("api_to_tools.auth._obtain_oauth2_token")
def test_get_token_returns_cached(mock_obtain):
    mock_obtain.return_value = _mock_token_response("tok_cached", 3600)
    auth = _oauth2_auth()
    mgr = TokenManager(auth)

    token1 = mgr.get_token()
    token2 = mgr.get_token()
    assert token1 == token2 == "tok_cached"
    assert mock_obtain.call_count == 1  # only fetched once


# ──────────────────────────────────────────────
# Expiry detection
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
def test_is_expired_when_no_token(mock_obtain):
    auth = _oauth2_auth()
    mgr = TokenManager(auth)
    assert mgr.is_expired is True


@patch("api_to_tools.auth._obtain_oauth2_token")
def test_is_expired_false_when_fresh(mock_obtain):
    mock_obtain.return_value = _mock_token_response(expires_in=3600)
    auth = _oauth2_auth()
    mgr = TokenManager(auth)
    mgr.get_token()
    assert mgr.is_expired is False


@patch("api_to_tools.auth._obtain_oauth2_token")
@patch("api_to_tools.auth.time")
def test_is_expired_true_when_past_expiry(mock_time, mock_obtain):
    mock_obtain.return_value = _mock_token_response(expires_in=60)
    # First call: monotonic returns 1000
    mock_time.monotonic.return_value = 1000.0
    auth = _oauth2_auth()
    mgr = TokenManager(auth)
    mgr.get_token()

    # After expiry - buffer: 1000 + 60 - 30 = 1030
    mock_time.monotonic.return_value = 1031.0
    assert mgr.is_expired is True


@patch("api_to_tools.auth._obtain_oauth2_token")
def test_no_expires_in_means_never_expired(mock_obtain):
    mock_obtain.return_value = _mock_token_response(expires_in=None)
    auth = _oauth2_auth()
    mgr = TokenManager(auth)
    mgr.get_token()
    assert mgr.is_expired is False


# ──────────────────────────────────────────────
# Auto-refresh on expiry
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
@patch("api_to_tools.auth.time")
def test_get_token_auto_refreshes_on_expiry(mock_time, mock_obtain):
    mock_obtain.side_effect = [
        _mock_token_response("tok_1", expires_in=60),
        _mock_token_response("tok_2", expires_in=3600),
    ]
    mock_time.monotonic.return_value = 1000.0
    auth = _oauth2_auth()
    mgr = TokenManager(auth)

    token1 = mgr.get_token()
    assert token1 == "tok_1"

    # Simulate time passing beyond expiry
    mock_time.monotonic.return_value = 1031.0
    token2 = mgr.get_token()
    assert token2 == "tok_2"
    assert mock_obtain.call_count == 2


# ──────────────────────────────────────────────
# Refresh token flow
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
def test_refresh_uses_refresh_token(mock_obtain):
    mock_obtain.return_value = _mock_token_response("tok_refreshed", refresh_token="rt_new")
    auth = _oauth2_auth(refresh_token="rt_original")
    mgr = TokenManager(auth)

    token = mgr.get_token()
    assert token == "tok_refreshed"
    # Check that _obtain_oauth2_token was called with a config containing the refresh_token
    called_auth = mock_obtain.call_args[0][0]
    assert called_auth.refresh_token == "rt_original"


@patch("api_to_tools.auth._obtain_oauth2_token")
def test_refresh_updates_refresh_token(mock_obtain):
    mock_obtain.side_effect = [
        _mock_token_response("tok_1", refresh_token="rt_2"),
        _mock_token_response("tok_2", refresh_token="rt_3"),
    ]
    auth = _oauth2_auth(refresh_token="rt_1")
    mgr = TokenManager(auth)

    mgr.get_token()
    assert mgr._refresh_token == "rt_2"

    mgr.refresh()
    assert mgr._refresh_token == "rt_3"


# ──────────────────────────────────────────────
# Force refresh
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
def test_force_refresh(mock_obtain):
    mock_obtain.side_effect = [
        _mock_token_response("tok_old"),
        _mock_token_response("tok_new"),
    ]
    auth = _oauth2_auth()
    mgr = TokenManager(auth)

    mgr.get_token()
    new_token = mgr.refresh()
    assert new_token == "tok_new"
    assert mock_obtain.call_count == 2


# ──────────────────────────────────────────────
# get_auth_header
# ──────────────────────────────────────────────

@patch("api_to_tools.auth._obtain_oauth2_token")
def test_get_auth_header(mock_obtain):
    mock_obtain.return_value = _mock_token_response("tok_header")
    auth = _oauth2_auth()
    mgr = TokenManager(auth)

    headers = mgr.get_auth_header()
    assert headers == {"Authorization": "Bearer tok_header"}
