import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from openhands.server.middleware import LocalhostCORSMiddleware, resolve_cors_origins


@pytest.fixture
def app():
    """Create a test FastAPI application."""
    app = FastAPI()

    @app.get('/test')
    def test_endpoint():
        return {'message': 'Test endpoint'}

    return app


def test_localhost_cors_middleware_init_with_env_var():
    """Test that the middleware correctly parses PERMITTED_CORS_ORIGINS environment variable."""
    with patch.dict(
        os.environ, {'PERMITTED_CORS_ORIGINS': 'https://example.com,https://test.com'}
    ):
        app = FastAPI()
        middleware = LocalhostCORSMiddleware(app)

        # Check that the origins were correctly parsed from the environment variable
        assert 'https://example.com' in middleware.allow_origins
        assert 'https://test.com' in middleware.allow_origins
        assert len(middleware.allow_origins) == 2


def test_localhost_cors_middleware_init_without_env_var():
    """Test that the middleware works correctly without PERMITTED_CORS_ORIGINS environment variable."""
    with patch.dict(os.environ, {}, clear=True):
        app = FastAPI()
        middleware = LocalhostCORSMiddleware(app)

        # Check that allow_origins is empty when no environment variable is set
        assert middleware.allow_origins == ()


def test_localhost_cors_middleware_is_allowed_origin_localhost(app):
    """Test that localhost origins are allowed regardless of port when no specific origins are configured."""
    # Test without setting PERMITTED_CORS_ORIGINS to trigger localhost behavior
    with patch.dict(os.environ, {}, clear=True):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # Test with localhost
        response = client.get('/test', headers={'Origin': 'http://localhost:8000'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://localhost:8000'
        )

        # Test with different port
        response = client.get('/test', headers={'Origin': 'http://localhost:3000'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://localhost:3000'
        )

        # Test with 127.0.0.1
        response = client.get('/test', headers={'Origin': 'http://127.0.0.1:8000'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://127.0.0.1:8000'
        )


def test_localhost_cors_middleware_is_allowed_origin_non_localhost(app):
    """Test that non-localhost origins follow the standard CORS rules."""
    # Set up the middleware with specific allowed origins
    with patch.dict(os.environ, {'PERMITTED_CORS_ORIGINS': 'https://example.com'}):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # Test with allowed origin
        response = client.get('/test', headers={'Origin': 'https://example.com'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'https://example.com'

        # Test with disallowed origin
        response = client.get('/test', headers={'Origin': 'https://disallowed.com'})
        assert response.status_code == 200
        # The disallowed origin should not be in the response headers
        assert 'access-control-allow-origin' not in response.headers


def test_localhost_cors_middleware_missing_origin(app):
    """Test behavior when Origin header is missing."""
    with patch.dict(os.environ, {}, clear=True):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # Test without Origin header
        response = client.get('/test')
        assert response.status_code == 200
        # There should be no access-control-allow-origin header
        assert 'access-control-allow-origin' not in response.headers


def test_localhost_cors_middleware_inheritance():
    """Test that LocalhostCORSMiddleware correctly inherits from CORSMiddleware."""
    assert issubclass(LocalhostCORSMiddleware, CORSMiddleware)


def test_localhost_cors_middleware_web_host_fallback():
    """Test that WEB_HOST env var is used as fallback when PERMITTED_CORS_ORIGINS is not set."""
    with patch.dict(os.environ, {'WEB_HOST': 'example.com'}, clear=True):
        app = FastAPI()
        middleware = LocalhostCORSMiddleware(app)

        assert 'https://example.com' in middleware.allow_origins
        assert 'http://example.com' in middleware.allow_origins
        assert len(middleware.allow_origins) == 2


def test_localhost_cors_middleware_web_host_allows_origin(app):
    """Test that WEB_HOST origins are actually allowed in requests."""
    with patch.dict(os.environ, {'WEB_HOST': 'example.com'}, clear=True):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # Test with https origin
        response = client.get('/test', headers={'Origin': 'https://example.com'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'https://example.com'

        # Test with http origin
        response = client.get('/test', headers={'Origin': 'http://example.com'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'http://example.com'

        # Test with disallowed origin
        response = client.get('/test', headers={'Origin': 'https://other.com'})
        assert response.status_code == 200
        assert 'access-control-allow-origin' not in response.headers


def test_localhost_cors_middleware_permitted_origins_takes_precedence():
    """Test that PERMITTED_CORS_ORIGINS takes precedence over WEB_HOST."""
    with patch.dict(
        os.environ,
        {
            'PERMITTED_CORS_ORIGINS': 'https://allowed.com',
            'WEB_HOST': 'example.com',
        },
        clear=True,
    ):
        app = FastAPI()
        middleware = LocalhostCORSMiddleware(app)

        # Only PERMITTED_CORS_ORIGINS should be used
        assert 'https://allowed.com' in middleware.allow_origins
        assert len(middleware.allow_origins) == 1
        assert 'https://example.com' not in middleware.allow_origins
        assert 'http://example.com' not in middleware.allow_origins


def test_localhost_cors_middleware_no_env_vars():
    """Test that localhost still works when no env vars are set."""
    with patch.dict(os.environ, {}, clear=True):
        app = FastAPI()
        middleware = LocalhostCORSMiddleware(app)

        # No explicit origins configured
        assert middleware.allow_origins == ()

        # But localhost should still be allowed via is_allowed_origin
        assert middleware.is_allowed_origin('http://localhost:3000') is True
        assert middleware.is_allowed_origin('http://127.0.0.1:8080') is True


def test_localhost_cors_middleware_localhost_works_with_web_host(app):
    """Test that localhost is still allowed when WEB_HOST is set."""
    with patch.dict(os.environ, {'WEB_HOST': 'example.com'}, clear=True):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # External origin should work
        response = client.get('/test', headers={'Origin': 'https://example.com'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'https://example.com'

        # Localhost should ALSO still work
        response = client.get('/test', headers={'Origin': 'http://localhost:3000'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://localhost:3000'
        )

        response = client.get('/test', headers={'Origin': 'http://127.0.0.1:3000'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://127.0.0.1:3000'
        )


def test_localhost_cors_middleware_localhost_works_with_permitted_origins(app):
    """Test that localhost is still allowed when PERMITTED_CORS_ORIGINS is set."""
    with patch.dict(
        os.environ, {'PERMITTED_CORS_ORIGINS': 'https://prod.example.com'}, clear=True
    ):
        app.add_middleware(LocalhostCORSMiddleware)
        client = TestClient(app)

        # Configured origin should work
        response = client.get('/test', headers={'Origin': 'https://prod.example.com'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin']
            == 'https://prod.example.com'
        )

        # Localhost should ALSO still work
        response = client.get('/test', headers={'Origin': 'http://localhost:3001'})
        assert response.status_code == 200
        assert (
            response.headers['access-control-allow-origin'] == 'http://localhost:3001'
        )


def testresolve_cors_origins_permitted_origins():
    """Test resolve_cors_origins with PERMITTED_CORS_ORIGINS."""
    with patch.dict(
        os.environ,
        {'PERMITTED_CORS_ORIGINS': 'https://a.com, https://b.com'},
        clear=True,
    ):
        result = resolve_cors_origins()
        assert result == ('https://a.com', 'https://b.com')


def testresolve_cors_origins_web_host():
    """Test resolve_cors_origins with WEB_HOST."""
    with patch.dict(os.environ, {'WEB_HOST': 'myserver.example.com'}, clear=True):
        result = resolve_cors_origins()
        assert result == (
            'https://myserver.example.com',
            'http://myserver.example.com',
        )


def testresolve_cors_origins_precedence():
    """Test that PERMITTED_CORS_ORIGINS takes precedence over WEB_HOST."""
    with patch.dict(
        os.environ,
        {'PERMITTED_CORS_ORIGINS': 'https://explicit.com', 'WEB_HOST': 'fallback.com'},
        clear=True,
    ):
        result = resolve_cors_origins()
        assert result == ('https://explicit.com',)


def testresolve_cors_origins_empty():
    """Test resolve_cors_origins with no env vars."""
    with patch.dict(os.environ, {}, clear=True):
        result = resolve_cors_origins()
        assert result == ()


def test_localhost_cors_middleware_cors_parameters():
    """Test that CORS parameters are set correctly in the middleware."""
    # We need to inspect the initialization parameters rather than attributes
    # since CORSMiddleware doesn't expose these as attributes
    with patch('fastapi.middleware.cors.CORSMiddleware.__init__') as mock_init:
        mock_init.return_value = None
        app = FastAPI()
        LocalhostCORSMiddleware(app)

        # Check that the parent class was initialized with the correct parameters
        mock_init.assert_called_once()
        _, kwargs = mock_init.call_args

        assert kwargs['allow_credentials'] is True
        assert kwargs['allow_methods'] == ['*']
        assert kwargs['allow_headers'] == ['*']


def test_resolve_cors_origins_strips_web_host_whitespace():
    """Test that WEB_HOST is stripped of whitespace."""
    with patch.dict(os.environ, {'WEB_HOST': '  example.com  '}, clear=True):
        result = resolve_cors_origins()
        assert result == ('https://example.com', 'http://example.com')


def test_resolve_cors_origins_empty_web_host():
    """Test that a whitespace-only WEB_HOST is treated as unset."""
    with patch.dict(os.environ, {'WEB_HOST': '   '}, clear=True):
        result = resolve_cors_origins()
        assert result == ()


def test_resolve_cors_origins_filters_empty_entries():
    """Test that empty entries from trailing commas are filtered out."""
    with patch.dict(
        os.environ, {'PERMITTED_CORS_ORIGINS': 'https://a.com,,https://b.com,'}, clear=True
    ):
        result = resolve_cors_origins()
        assert result == ('https://a.com', 'https://b.com')


try:
    import socketio as _socketio  # noqa: F401

    _has_socketio = True
except ImportError:
    _has_socketio = False


@pytest.mark.skipif(not _has_socketio, reason='socketio not installed')
def test_get_cors_origins_includes_localhost_when_web_host_set():
    """Test that Socket.IO CORS origins include localhost when WEB_HOST is set."""
    from openhands.server.shared import _get_cors_origins

    with patch.dict(os.environ, {'WEB_HOST': 'example.com'}, clear=True):
        origins = _get_cors_origins()
        assert isinstance(origins, list)
        # External origins present
        assert 'https://example.com' in origins
        assert 'http://example.com' in origins
        # Localhost origins present for dev
        assert 'http://localhost:3000' in origins
        assert 'http://localhost:3001' in origins
        assert 'http://127.0.0.1:3000' in origins


@pytest.mark.skipif(not _has_socketio, reason='socketio not installed')
def test_get_cors_origins_includes_localhost_when_permitted_origins_set():
    """Test that Socket.IO CORS origins include localhost when PERMITTED_CORS_ORIGINS is set."""
    from openhands.server.shared import _get_cors_origins

    with patch.dict(
        os.environ, {'PERMITTED_CORS_ORIGINS': 'https://prod.example.com'}, clear=True
    ):
        origins = _get_cors_origins()
        assert isinstance(origins, list)
        assert 'https://prod.example.com' in origins
        assert 'http://localhost:3000' in origins
        assert 'http://localhost:3001' in origins


@pytest.mark.skipif(not _has_socketio, reason='socketio not installed')
def test_get_cors_origins_wildcard_when_no_env():
    """Test that Socket.IO CORS origins default to '*' when no env vars are set."""
    from openhands.server.shared import _get_cors_origins

    with patch.dict(os.environ, {}, clear=True):
        origins = _get_cors_origins()
        assert origins == '*'
