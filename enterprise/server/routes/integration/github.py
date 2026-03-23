import hashlib
import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from openhands.core.logger import openhands_logger as logger

github_integration_router = APIRouter(prefix='/integration')

# Lazy-initialized singleton for GitHub manager
_github_manager = None


def _get_github_manager():
    """Get the GitHub manager singleton, initializing it lazily if needed.

    This lazy initialization pattern allows the module to be imported without
    requiring environment variables to be set, which is useful for testing.
    """
    global _github_manager
    if _github_manager is None:
        from integrations.github.data_collector import GitHubDataCollector
        from integrations.github.github_manager import GithubManager
        from server.auth.token_manager import TokenManager

        token_manager = TokenManager()
        data_collector = GitHubDataCollector()
        _github_manager = GithubManager(token_manager, data_collector)
    return _github_manager


def _get_webhook_secret() -> str:
    """Get the GitHub webhook secret from environment.

    This function reads the secret at runtime rather than import time,
    allowing the module to be imported without environment variables set.
    """
    return os.environ.get('GITHUB_APP_WEBHOOK_SECRET', '')


def _is_webhooks_enabled() -> bool:
    """Check if GitHub webhooks are enabled.

    Reads the environment variable at runtime for testability.
    """
    return os.environ.get('GITHUB_WEBHOOKS_ENABLED', '1') in ('1', 'true')


def verify_github_signature(payload: bytes, signature: str):
    if not signature:
        raise HTTPException(
            status_code=403, detail='x-hub-signature-256 header is missing!'
        )

    webhook_secret = _get_webhook_secret()
    expected_signature = (
        'sha256='
        + hmac.new(
            webhook_secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Request signatures didn't match!")


@github_integration_router.post('/github/events')
async def github_events(
    request: Request,
    x_hub_signature_256: str = Header(None),
):
    # Check if GitHub webhooks are enabled
    if not _is_webhooks_enabled():
        logger.info(
            'GitHub webhooks are disabled by GITHUB_WEBHOOKS_ENABLED environment variable'
        )
        return JSONResponse(
            status_code=200,
            content={'message': 'GitHub webhooks are currently disabled.'},
        )

    try:
        payload = await request.body()
        verify_github_signature(payload, x_hub_signature_256)

        payload_data = await request.json()
        installation_id = payload_data.get('installation', {}).get('id')

        if not installation_id:
            return JSONResponse(
                status_code=400,
                content={'error': 'Installation ID is missing in the payload.'},
            )

        # Import Message and SourceType lazily to avoid import-time dependencies
        from integrations.models import Message, SourceType

        message_payload = {'payload': payload_data, 'installation': installation_id}
        message = Message(source=SourceType.GITHUB, message=message_payload)
        await _get_github_manager().receive_message(message)

        return JSONResponse(
            status_code=200,
            content={'message': 'GitHub events endpoint reached successfully.'},
        )
    except ClientDisconnect:
        logger.debug('GitHub webhook client disconnected before completing request')
        return JSONResponse(
            status_code=499,
            content={'error': 'Client disconnected.'},
        )
    except Exception as e:
        logger.exception(f'Error processing GitHub event: {e}')
        return JSONResponse(status_code=400, content={'error': 'Invalid payload.'})
