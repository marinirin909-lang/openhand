"""Tests for httpx_utils module."""

import httpx

from openhands.app_server.utils.httpx_utils import extract_error_detail


class TestExtractErrorDetail:
    """Tests for extract_error_detail function."""

    def test_httpx_error_with_exception_field(self):
        """Should extract 'exception' field from JSON response."""
        response = httpx.Response(
            500,
            json={
                'detail': 'Internal Server Error',
                'exception': "Client error '401 Unauthorized' for url 'https://mcp.atlassian.com/v1/sse'",
            },
        )
        response._request = httpx.Request(
            'POST', 'https://example.com/api/conversations'
        )
        exc = httpx.HTTPStatusError(
            message='Server error',
            request=response.request,
            response=response,
        )

        result = extract_error_detail(exc)
        assert (
            result
            == "Client error '401 Unauthorized' for url 'https://mcp.atlassian.com/v1/sse'"
        )

    def test_httpx_error_with_detail_field_only(self):
        """Should extract 'detail' field when 'exception' is not present."""
        response = httpx.Response(
            400,
            json={'detail': 'Bad Request: Invalid input'},
        )
        response._request = httpx.Request('POST', 'https://example.com/api')
        exc = httpx.HTTPStatusError(
            message='Client error',
            request=response.request,
            response=response,
        )

        result = extract_error_detail(exc)
        assert result == 'Bad Request: Invalid input'

    def test_httpx_error_with_other_json(self):
        """Should return raw text when JSON has neither 'exception' nor 'detail'."""
        response = httpx.Response(
            500,
            json={'error': 'Something went wrong', 'code': 123},
        )
        response._request = httpx.Request('POST', 'https://example.com/api')
        exc = httpx.HTTPStatusError(
            message='Server error',
            request=response.request,
            response=response,
        )

        result = extract_error_detail(exc)
        assert 'Something went wrong' in result

    def test_httpx_error_with_non_json_response(self):
        """Should fall back to str(exc) when response is not JSON."""
        response = httpx.Response(
            500,
            text='Internal Server Error',
            headers={'content-type': 'text/plain'},
        )
        response._request = httpx.Request('POST', 'https://example.com/api')
        exc = httpx.HTTPStatusError(
            message='Server error',
            request=response.request,
            response=response,
        )

        result = extract_error_detail(exc)
        # Should contain the URL since str(HTTPStatusError) includes it
        assert 'example.com' in result or 'Server error' in result

    def test_non_httpx_exception(self):
        """Should return str(exc) for non-HTTPStatusError exceptions."""
        exc = ValueError('Something went wrong')
        result = extract_error_detail(exc)
        assert result == 'Something went wrong'

    def test_generic_exception(self):
        """Should return str(exc) for generic exceptions."""
        exc = Exception('Generic error')
        result = extract_error_detail(exc)
        assert result == 'Generic error'

    def test_mcp_401_error_scenario(self):
        """Test the actual MCP 401 error scenario that triggered this fix."""
        response = httpx.Response(
            500,
            json={
                'detail': 'Internal Server Error',
                'exception': "Client error '401 Unauthorized' for url 'https://mcp.atlassian.com/v1/sse'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
            },
        )
        response._request = httpx.Request(
            'POST', 'https://example.prod-runtime.all-hands.dev/api/conversations'
        )
        exc = httpx.HTTPStatusError(
            message="Server error '500 Internal Server Error'",
            request=response.request,
            response=response,
        )

        result = extract_error_detail(exc)

        # The result should contain the actual MCP error, not just the generic 500 message
        assert 'mcp.atlassian.com' in result
        assert '401 Unauthorized' in result
