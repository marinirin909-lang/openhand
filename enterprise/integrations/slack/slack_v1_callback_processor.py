import logging
from uuid import UUID

from integrations.utils import CONVERSATION_URL
from integrations.v1_utils import handle_callback_error
from pydantic import Field
from slack_sdk import WebClient
from storage.slack_team_store import SlackTeamStore

from openhands.agent_server.models import EventSortOrder
from openhands.app_server.event_callback.event_callback_models import (
    EventCallback,
    EventCallbackProcessor,
)
from openhands.app_server.event_callback.event_callback_result_models import (
    EventCallbackResult,
    EventCallbackResultStatus,
)
from openhands.sdk import Event, MessageEvent, TextContent
from openhands.sdk.event import ConversationStateUpdateEvent

_logger = logging.getLogger(__name__)

ASSISTANT_SOURCE = 'agent'
FALLBACK_MESSAGE = (
    'No response from the agent.\n\n<{conversation_url}|See the conversation>'
)


def _slack_conversation_link(conversation_id: UUID) -> str:
    """Format conversation URL for Slack mrkdwn (<url|label>)."""
    url = CONVERSATION_URL.format(conversation_id)
    return f'<{url}|See the conversation>'


class SlackV1CallbackProcessor(EventCallbackProcessor):
    """Callback processor for Slack V1 integrations."""

    slack_view_data: dict[str, str | None] = Field(default_factory=dict)

    async def __call__(
        self,
        conversation_id: UUID,
        callback: EventCallback,
        event: Event,
    ) -> EventCallbackResult | None:
        """Process events for Slack V1 integration."""
        # Only handle ConversationStateUpdateEvent
        if not isinstance(event, ConversationStateUpdateEvent):
            return None

        # Only act when execution has finished
        if not (event.key == 'execution_status' and event.value == 'finished'):
            return None

        _logger.info('[Slack V1] Callback agent state was %s', event)

        try:
            message = await self._get_final_assistant_message(conversation_id)
            await self._post_message_to_slack(message)

            return EventCallbackResult(
                status=EventCallbackResultStatus.SUCCESS,
                event_callback_id=callback.id,
                event_id=event.id,
                conversation_id=conversation_id,
                detail=message,
            )
        except Exception as e:
            can_post_error = bool(self.slack_view_data.get('team_id'))
            await handle_callback_error(
                error=e,
                conversation_id=conversation_id,
                service_name='Slack',
                service_logger=_logger,
                can_post_error=can_post_error,
                post_error_func=self._post_message_to_slack,
            )

            return EventCallbackResult(
                status=EventCallbackResultStatus.ERROR,
                event_callback_id=callback.id,
                event_id=event.id,
                conversation_id=conversation_id,
                detail=str(e),
            )

    # -------------------------------------------------------------------------
    # Slack helpers
    # -------------------------------------------------------------------------

    async def _get_bot_access_token(self) -> str | None:
        team_id = self.slack_view_data.get('team_id')
        if team_id is None:
            return None
        slack_team_store = SlackTeamStore.get_instance()
        bot_access_token = await slack_team_store.get_team_bot_token(team_id)

        return bot_access_token

    async def _post_message_to_slack(self, message: str) -> None:
        """Post a message to the configured Slack channel (threaded reply)."""
        bot_access_token = await self._get_bot_access_token()
        if not bot_access_token:
            raise RuntimeError('Missing Slack bot access token')

        channel_id = self.slack_view_data['channel_id']
        thread_ts = self.slack_view_data.get('thread_ts') or self.slack_view_data.get(
            'message_ts'
        )

        client = WebClient(token=bot_access_token)

        try:
            response = client.chat_postMessage(
                channel=channel_id,
                text=message,
                thread_ts=thread_ts,
                unfurl_links=False,
                unfurl_media=False,
            )

            if not response['ok']:
                raise RuntimeError(
                    f'Slack API error: {response.get("error", "Unknown error")}'
                )

            _logger.info(
                '[Slack V1] Successfully posted message to channel %s', channel_id
            )

        except Exception as e:
            _logger.error('[Slack V1] Failed to post message to Slack: %s', e)
            raise

    # -------------------------------------------------------------------------
    # Final assistant message (from EventService)
    # -------------------------------------------------------------------------

    async def _get_final_assistant_message(self, conversation_id: UUID) -> str:
        """Fetch the most recent assistant message from EventService and return its content.

        Returns a fallback message with conversation link if none found.
        """
        from openhands.app_server.config import get_event_service
        from openhands.app_server.services.injector import InjectorState
        from openhands.app_server.user.specifiy_user_context import (
            ADMIN,
            USER_CONTEXT_ATTR,
        )

        state = InjectorState()
        setattr(state, USER_CONTEXT_ATTR, ADMIN)

        try:
            async with get_event_service(state) as event_service:
                page = await event_service.search_events(
                    conversation_id=conversation_id,
                    kind__eq='MessageEvent',
                    sort_order=EventSortOrder.TIMESTAMP_DESC,
                    limit=50,
                )
        except Exception as e:
            _logger.warning(
                '[Slack V1] Failed to search events for %s: %s',
                conversation_id,
                e,
                exc_info=True,
            )
            return FALLBACK_MESSAGE.format(
                conversation_url=CONVERSATION_URL.format(conversation_id)
            )

        if not page or not page.items:
            return FALLBACK_MESSAGE.format(
                conversation_url=CONVERSATION_URL.format(conversation_id)
            )

        for evt in page.items:
            if not isinstance(evt, MessageEvent):
                continue
            if evt.source != ASSISTANT_SOURCE:
                continue
            llm_message = getattr(evt, 'llm_message', None)
            if llm_message is not None:
                role = getattr(llm_message, 'role', None)
                if role is not None and role != 'assistant':
                    continue
            text = self._extract_message_text(evt)
            if text:
                return text

        return FALLBACK_MESSAGE.format(
            conversation_url=CONVERSATION_URL.format(conversation_id)
        )

    @staticmethod
    def _extract_message_text(evt: MessageEvent) -> str | None:
        """Extract plain text from a MessageEvent's llm_message content blocks."""
        llm_message = getattr(evt, 'llm_message', None)
        if llm_message is None:
            return None
        content_blocks = getattr(llm_message, 'content', None)
        if not content_blocks:
            return None
        parts: list[str] = []
        for block in content_blocks:
            if isinstance(block, TextContent):
                text = block.text.strip()
                if text:
                    parts.append(text)
        return '\n\n'.join(parts) if parts else None
