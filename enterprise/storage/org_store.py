"""
Store class for managing organizations.
"""

from typing import Any, Optional
from uuid import UUID

from server.constants import (
    DEFAULT_V1_ENABLED,
    LITE_LLM_API_URL,
    ORG_SETTINGS_VERSION,
    get_default_litellm_model,
)
from server.routes.org_models import OrgLLMSettingsUpdate, OrphanedUserError
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload
from storage.database import a_session_maker
from storage.lite_llm_manager import LiteLlmManager
from storage.org import Org
from storage.org_member import OrgMember
from storage.user import User
from storage.user_settings import UserSettings

from openhands.core.logger import openhands_logger as logger
from openhands.storage.data_models.settings import Settings

# Only these agent_settings keys are stored on org; user/member secrets remain elsewhere.
_ORG_SCOPED_AGENT_SETTINGS_KEYS = {
    'schema_version',
    'agent',
    'llm.model',
    'llm.base_url',
    'verification.confirmation_mode',
    'verification.security_analyzer',
    'condenser.enabled',
    'condenser.max_size',
    'max_iterations',
    'mcp_config',
}


class OrgStore:
    """Store for managing organizations."""

    @staticmethod
    def org_scoped_agent_settings(agent_settings: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in agent_settings.items()
            if key in _ORG_SCOPED_AGENT_SETTINGS_KEYS
        }

    @staticmethod
    def get_agent_settings_from_org(org: Org) -> dict[str, Any]:
        raw_agent_settings = getattr(org, 'agent_settings', {})
        if not isinstance(raw_agent_settings, dict):
            raw_agent_settings = {}

        settings = Settings(agent_settings=dict(raw_agent_settings))
        settings.set_agent_setting('agent', getattr(org, 'agent', None))
        settings.set_agent_setting('llm.model', getattr(org, 'default_llm_model', None))
        settings.set_agent_setting(
            'llm.base_url', getattr(org, 'default_llm_base_url', None)
        )
        settings.set_agent_setting(
            'verification.confirmation_mode', getattr(org, 'confirmation_mode', None)
        )
        settings.set_agent_setting(
            'verification.security_analyzer', getattr(org, 'security_analyzer', None)
        )
        settings.set_agent_setting(
            'condenser.enabled', getattr(org, 'enable_default_condenser', None)
        )
        settings.set_agent_setting(
            'condenser.max_size', getattr(org, 'condenser_max_size', None)
        )
        settings.set_agent_setting(
            'max_iterations', getattr(org, 'default_max_iterations', None)
        )
        settings.set_agent_setting('mcp_config', getattr(org, 'mcp_config', None))
        return OrgStore.org_scoped_agent_settings(
            settings.normalized_agent_settings(strip_secret_values=True)
        )

    @staticmethod
    def sync_agent_settings(org: Org) -> None:
        org.agent_settings = OrgStore.get_agent_settings_from_org(org)

    @staticmethod
    async def create_org(
        kwargs: dict,
    ) -> Org:
        """Create a new organization."""
        async with a_session_maker() as session:
            org = Org(**kwargs)
            org.org_version = ORG_SETTINGS_VERSION
            if org.default_llm_model is None:
                org.default_llm_model = get_default_litellm_model()
            if org.v1_enabled is None:
                org.v1_enabled = DEFAULT_V1_ENABLED
            OrgStore.sync_agent_settings(org)
            session.add(org)
            await session.commit()
            await session.refresh(org)
            return org

    @staticmethod
    async def get_org_by_id(org_id: UUID) -> Org | None:
        """Get organization by ID."""
        async with a_session_maker() as session:
            result = await session.execute(select(Org).filter(Org.id == org_id))
            org = result.scalars().first()
        return await OrgStore._validate_org_version(org)

    @staticmethod
    async def get_current_org_from_keycloak_user_id(
        keycloak_user_id: str,
    ) -> Org | None:
        async with a_session_maker() as session:
            result = await session.execute(
                select(User)
                .options(joinedload(User.org_members))
                .filter(User.id == UUID(keycloak_user_id))
            )
            user = result.scalars().first()
            if not user:
                logger.warning(f'User not found for ID {keycloak_user_id}')
                return None
            org_id = user.current_org_id
            result = await session.execute(select(Org).filter(Org.id == org_id))
            org = result.scalars().first()
            if not org:
                logger.warning(
                    f'Org not found for ID {org_id} as the current org for user {keycloak_user_id}'
                )
                return None
            return await OrgStore._validate_org_version(org)

    @staticmethod
    async def get_org_by_name(name: str) -> Org | None:
        """Get organization by name."""
        async with a_session_maker() as session:
            result = await session.execute(select(Org).filter(Org.name == name))
            org = result.scalars().first()
        return await OrgStore._validate_org_version(org)

    @staticmethod
    async def _validate_org_version(org: Org | None) -> Org | None:
        """Check if we need to update org version."""
        if org and org.org_version < ORG_SETTINGS_VERSION:
            org = await OrgStore.update_org(
                org.id,
                {
                    'org_version': ORG_SETTINGS_VERSION,
                    'default_llm_model': get_default_litellm_model(),
                    'default_llm_base_url': LITE_LLM_API_URL,
                },
            )
        return org

    @staticmethod
    async def list_orgs() -> list[Org]:
        """List all organizations."""
        async with a_session_maker() as session:
            result = await session.execute(select(Org))
            orgs = result.scalars().all()
            return list(orgs)

    @staticmethod
    async def get_user_orgs_paginated(
        user_id: UUID, page_id: str | None = None, limit: int = 100
    ) -> tuple[list[Org], str | None]:
        """
        Get paginated list of organizations for a user.

        Args:
            user_id: User UUID
            page_id: Optional page ID (offset as string) for pagination
            limit: Maximum number of organizations to return

        Returns:
            Tuple of (list of Org objects, next_page_id or None)
        """
        async with a_session_maker() as session:
            # Build query joining OrgMember with Org
            query = (
                select(Org)
                .join(OrgMember, Org.id == OrgMember.org_id)
                .filter(OrgMember.user_id == user_id)
                .order_by(Org.name)
            )

            # Apply pagination offset
            if page_id is not None:
                try:
                    offset = int(page_id)
                    query = query.offset(offset)
                except ValueError:
                    # If page_id is not a valid integer, start from beginning
                    offset = 0
            else:
                offset = 0

            # Fetch limit + 1 to check if there are more results
            query = query.limit(limit + 1)
            result = await session.execute(query)
            orgs = list(result.scalars().all())

            # Check if there are more results
            has_more = len(orgs) > limit
            if has_more:
                orgs = orgs[:limit]

            # Calculate next page ID
            next_page_id = None
            if has_more:
                next_page_id = str(offset + limit)

            # Validate org versions
            validated_orgs = []
            for org in orgs:
                if org:
                    validated = await OrgStore._validate_org_version(org)
                    if validated is not None:
                        validated_orgs.append(validated)

            return validated_orgs, next_page_id

    @staticmethod
    async def update_org(
        org_id: UUID,
        kwargs: dict,
    ) -> Optional[Org]:
        """Update organization details."""
        async with a_session_maker() as session:
            result = await session.execute(select(Org).filter(Org.id == org_id))
            org = result.scalars().first()
            if not org:
                return None

            if 'id' in kwargs:
                kwargs.pop('id')
            for key, value in kwargs.items():
                if hasattr(org, key):
                    setattr(org, key, value)

            OrgStore.sync_agent_settings(org)
            await session.commit()
            await session.refresh(org)
            return org

    @staticmethod
    def get_kwargs_from_settings(settings: Settings):
        agent_settings = settings.to_agent_settings()
        return {
            'agent': agent_settings.agent,
            'default_max_iterations': settings.get_agent_setting('max_iterations'),
            'security_analyzer': agent_settings.verification.security_analyzer,
            'confirmation_mode': agent_settings.verification.confirmation_mode,
            'default_llm_model': agent_settings.llm.model,
            'default_llm_base_url': agent_settings.llm.base_url,
            'remote_runtime_resource_factor': getattr(
                settings, 'remote_runtime_resource_factor', None
            ),
            'enable_default_condenser': agent_settings.condenser.enabled,
            'billing_margin': getattr(settings, 'billing_margin', None),
            'enable_proactive_conversation_starters': getattr(
                settings, 'enable_proactive_conversation_starters', None
            ),
            'sandbox_base_container_image': getattr(
                settings, 'sandbox_base_container_image', None
            ),
            'sandbox_runtime_container_image': getattr(
                settings, 'sandbox_runtime_container_image', None
            ),
            'search_api_key': getattr(settings, 'search_api_key', None),
            'sandbox_api_key': getattr(settings, 'sandbox_api_key', None),
            'max_budget_per_task': getattr(settings, 'max_budget_per_task', None),
            'enable_solvability_analysis': getattr(
                settings, 'enable_solvability_analysis', None
            ),
            'v1_enabled': getattr(settings, 'v1_enabled', None),
            'conversation_expiration': getattr(
                settings, 'conversation_expiration', None
            ),
            'condenser_max_size': settings.get_agent_setting('condenser.max_size'),
            'byor_export_enabled': getattr(settings, 'byor_export_enabled', None),
            'sandbox_grouping_strategy': getattr(
                settings, 'sandbox_grouping_strategy', None
            ),
            'agent_settings': OrgStore.org_scoped_agent_settings(
                settings.normalized_agent_settings(strip_secret_values=True)
            ),
            'mcp_config': agent_settings.mcp_config,
        }

    @staticmethod
    def get_kwargs_from_user_settings(user_settings: UserSettings):
        settings = user_settings.to_settings()
        agent_settings = settings.to_agent_settings()
        return {
            'agent': agent_settings.agent,
            'default_max_iterations': settings.get_agent_setting('max_iterations'),
            'security_analyzer': agent_settings.verification.security_analyzer,
            'confirmation_mode': agent_settings.verification.confirmation_mode,
            'default_llm_model': agent_settings.llm.model,
            'default_llm_base_url': agent_settings.llm.base_url,
            'remote_runtime_resource_factor': user_settings.remote_runtime_resource_factor,
            'enable_default_condenser': agent_settings.condenser.enabled,
            'billing_margin': user_settings.billing_margin,
            'enable_proactive_conversation_starters': user_settings.enable_proactive_conversation_starters,
            'sandbox_base_container_image': user_settings.sandbox_base_container_image,
            'sandbox_runtime_container_image': user_settings.sandbox_runtime_container_image,
            'org_version': user_settings.user_version,
            'agent_settings': OrgStore.org_scoped_agent_settings(
                settings.normalized_agent_settings(strip_secret_values=True)
            ),
            'mcp_config': agent_settings.mcp_config,
            'search_api_key': user_settings.search_api_key,
            'sandbox_api_key': user_settings.sandbox_api_key,
            'max_budget_per_task': user_settings.max_budget_per_task,
            'enable_solvability_analysis': user_settings.enable_solvability_analysis,
            'v1_enabled': user_settings.v1_enabled,
            'condenser_max_size': agent_settings.condenser.max_size,
            'sandbox_grouping_strategy': user_settings.sandbox_grouping_strategy,
        }

    @staticmethod
    async def persist_org_with_owner(
        org: Org,
        org_member: OrgMember,
    ) -> Org:
        """
        Persist organization and owner membership in a single transaction.

        Args:
            org: Organization entity to persist
            org_member: Organization member entity to persist

        Returns:
            Org: The persisted organization object

        Raises:
            Exception: If database operations fail
        """
        async with a_session_maker() as session:
            session.add(org)
            session.add(org_member)
            await session.commit()
            await session.refresh(org)
            return org

    @staticmethod
    async def delete_org_cascade(org_id: UUID) -> Org | None:
        """
        Delete organization and all associated data in cascade, including external LiteLLM cleanup.

        Args:
            org_id: UUID of the organization to delete

        Returns:
            Org: The deleted organization object, or None if not found

        Raises:
            Exception: If database operations or LiteLLM cleanup fail
        """
        async with a_session_maker() as session:
            # First get the organization to return it
            result = await session.execute(select(Org).filter(Org.id == org_id))
            org = result.scalars().first()
            if not org:
                return None

            try:
                # 1. Delete conversation data for organization conversations
                await session.execute(
                    text("""
                    DELETE FROM conversation_metadata
                    WHERE conversation_id IN (
                        SELECT conversation_id FROM conversation_metadata_saas WHERE org_id = :org_id
                    )
                    """),
                    {'org_id': str(org_id)},
                )

                await session.execute(
                    text("""
                    DELETE FROM app_conversation_start_task
                    WHERE app_conversation_id IN (
                        SELECT conversation_id::uuid FROM conversation_metadata_saas WHERE org_id = :org_id
                    )
                    """),
                    {'org_id': str(org_id)},
                )

                # 2. Delete organization-owned data tables (direct org_id foreign keys)
                await session.execute(
                    text('DELETE FROM billing_sessions WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text(
                        'DELETE FROM conversation_metadata_saas WHERE org_id = :org_id'
                    ),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text('DELETE FROM custom_secrets WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text('DELETE FROM api_keys WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text('DELETE FROM slack_conversation WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text('DELETE FROM slack_users WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )
                await session.execute(
                    text('DELETE FROM stripe_customers WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )

                # 3. Handle users with this as current_org_id BEFORE deleting memberships
                # Single query to find orphaned users (those with no alternative org)
                orphaned_result = await session.execute(
                    text("""
                        SELECT u.id
                        FROM "user" u
                        WHERE u.current_org_id = :org_id
                        AND NOT EXISTS (
                            SELECT 1 FROM org_member om
                            WHERE om.user_id = u.id AND om.org_id != :org_id
                        )
                    """),
                    {'org_id': str(org_id)},
                )
                orphaned_users = orphaned_result.fetchall()

                if orphaned_users:
                    raise OrphanedUserError([str(row[0]) for row in orphaned_users])

                # Batch update: reassign current_org_id to an alternative org for all affected users
                await session.execute(
                    text("""
                        UPDATE "user"
                        SET current_org_id = (
                            SELECT om.org_id FROM org_member om
                            WHERE om.user_id = "user".id AND om.org_id != :org_id
                            LIMIT 1
                        )
                        WHERE "user".current_org_id = :org_id
                    """),
                    {'org_id': str(org_id)},
                )

                # 4. Delete organization memberships (now safe)
                await session.execute(
                    text('DELETE FROM org_member WHERE org_id = :org_id'),
                    {'org_id': str(org_id)},
                )

                # 5. Finally delete the organization
                session.delete(org)

                # 6. Clean up LiteLLM team before committing transaction
                logger.info(
                    'Deleting LiteLLM team within database transaction',
                    extra={'org_id': str(org_id)},
                )
                await LiteLlmManager.delete_team(str(org_id))

                # 7. Commit all changes only if everything succeeded
                await session.commit()

                logger.info(
                    'Successfully deleted organization and all associated data including LiteLLM team',
                    extra={'org_id': str(org_id), 'org_name': org.name},
                )

                return org

            except Exception as e:
                await session.rollback()
                logger.error(
                    'Failed to delete organization - transaction rolled back',
                    extra={'org_id': str(org_id), 'error': str(e)},
                )
                raise

    @staticmethod
    async def get_org_by_id_async(org_id: UUID) -> Org | None:
        """Get organization by ID (async version).

        Note: This method is kept for backwards compatibility but simply
        delegates to get_org_by_id which is now async.
        """
        return await OrgStore.get_org_by_id(org_id)

    @staticmethod
    async def update_org_llm_settings_async(
        org_id: UUID,
        llm_settings: OrgLLMSettingsUpdate,
    ) -> Org | None:
        """Update organization LLM settings and propagate to members (async version).

        Args:
            org_id: Organization ID
            llm_settings: Typed LLM settings update model

        Returns:
            Updated Org or None if not found
        """
        from storage.org_member_store import OrgMemberStore

        async with a_session_maker() as session:
            result = await session.execute(select(Org).filter(Org.id == org_id))
            org = result.scalars().first()
            if not org:
                return None

            # Apply updates to org
            llm_settings.apply_to_org(org)
            OrgStore.sync_agent_settings(org)

            # Propagate relevant settings to all org members
            member_updates = llm_settings.get_member_updates()
            if member_updates:
                await OrgMemberStore.update_all_members_llm_settings_async(
                    session, org_id, member_updates
                )

            await session.commit()
            await session.refresh(org)
            return org
