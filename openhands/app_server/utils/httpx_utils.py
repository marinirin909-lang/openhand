"""Utilities for working with httpx HTTP client."""

import httpx


def extract_error_detail(exc: Exception) -> str:
    """Extract detailed error message from an exception.

    For httpx.HTTPStatusError, attempts to extract the error details from
    the response body (JSON 'exception' or 'detail' field, or raw text).
    For other exceptions, returns str(exc).

    Args:
        exc: The exception to extract details from.

    Returns:
        A detailed error message string.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            error_body = exc.response.json()
            # Prefer 'exception' field if available (contains the actual error)
            if 'exception' in error_body:
                return error_body['exception']
            elif 'detail' in error_body:
                return error_body['detail']
            else:
                return exc.response.text
        except Exception:
            # If we can't parse the response, fall back to the basic error
            return str(exc)
    return str(exc)
