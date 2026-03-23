"""Usage statistics API endpoint for organization dashboards.

Provides aggregated metrics for organization admins and owners including:
- Total conversation count
- Merged PR count
- Average conversation cost
- Daily conversation counts for the last 90 days
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from server.auth.authorization import Permission, require_permission
from sqlalchemy import and_, func, select
from storage.database import a_session_maker
from storage.openhands_pr import OpenhandsPR
from storage.stored_conversation_metadata import StoredConversationMetadata
from storage.stored_conversation_metadata_saas import StoredConversationMetadataSaas

from openhands.core.logger import openhands_logger as logger

usage_router = APIRouter(prefix="/api/organizations", tags=["Usage"])


class DailyConversationCount(BaseModel):
    """Daily conversation count for a specific date."""

    date: str  # ISO date format YYYY-MM-DD
    count: int


class UsageStatsResponse(BaseModel):
    """Response model for organization usage statistics."""

    total_conversations: int
    merged_prs: int
    average_cost: float
    daily_conversations: list[DailyConversationCount]


@usage_router.get(
    "/{org_id}/usage",
    response_model=UsageStatsResponse,
    dependencies=[Depends(require_permission(Permission.VIEW_BILLING))],
)
async def get_org_usage_stats(
    org_id: UUID,
) -> UsageStatsResponse:
    """Get usage statistics for an organization.

    This endpoint returns aggregated usage metrics for the specified organization:
    - Total number of conversations
    - Number of merged PRs created by OpenHands
    - Average cost per conversation
    - Daily conversation counts for the last 90 days

    Only users with VIEW_BILLING permission (admin or owner) can access this endpoint.

    Args:
        org_id: Organization ID (UUID)

    Returns:
        UsageStatsResponse: Aggregated usage statistics

    Raises:
        HTTPException: 403 if user doesn't have permission
        HTTPException: 500 if retrieval fails
    """
    logger.info(
        "Fetching usage statistics for organization",
        extra={"org_id": str(org_id)},
    )

    try:
        async with a_session_maker() as session:
            # Get total conversation count for this org
            total_conversations_result = await session.execute(
                select(
                    func.count(StoredConversationMetadataSaas.conversation_id)
                ).where(StoredConversationMetadataSaas.org_id == org_id)
            )
            total_conversations = total_conversations_result.scalar() or 0

            # Get average cost - join with conversation metadata to get accumulated_cost
            avg_cost_result = await session.execute(
                select(func.avg(StoredConversationMetadata.accumulated_cost))
                .select_from(StoredConversationMetadata)
                .join(
                    StoredConversationMetadataSaas,
                    StoredConversationMetadata.conversation_id
                    == StoredConversationMetadataSaas.conversation_id,
                )
                .where(StoredConversationMetadataSaas.org_id == org_id)
            )
            average_cost = avg_cost_result.scalar() or 0.0

            # Get merged PRs count
            # Note: OpenhandsPR doesn't have org_id directly, so we need to join via conversations
            # For now, we'll count all merged PRs that are associated with conversations in this org
            merged_prs_result = await session.execute(
                select(func.count(func.distinct(OpenhandsPR.id)))
                .select_from(OpenhandsPR)
                .join(
                    StoredConversationMetadata,
                    and_(
                        StoredConversationMetadata.selected_repository
                        == OpenhandsPR.repo_name,
                        StoredConversationMetadata.pr_number.contains(
                            [OpenhandsPR.pr_number]
                        ),
                    ),
                )
                .join(
                    StoredConversationMetadataSaas,
                    StoredConversationMetadata.conversation_id
                    == StoredConversationMetadataSaas.conversation_id,
                )
                .where(
                    and_(
                        StoredConversationMetadataSaas.org_id == org_id,
                        OpenhandsPR.merged.is_(True),
                    )
                )
            )
            merged_prs = merged_prs_result.scalar() or 0

            # Get daily conversation counts for the last 90 days
            ninety_days_ago = datetime.now(UTC) - timedelta(days=90)
            daily_counts_result = await session.execute(
                select(
                    func.date(StoredConversationMetadata.created_at).label("date"),
                    func.count(StoredConversationMetadata.conversation_id).label(
                        "count"
                    ),
                )
                .select_from(StoredConversationMetadata)
                .join(
                    StoredConversationMetadataSaas,
                    StoredConversationMetadata.conversation_id
                    == StoredConversationMetadataSaas.conversation_id,
                )
                .where(
                    and_(
                        StoredConversationMetadataSaas.org_id == org_id,
                        StoredConversationMetadata.created_at >= ninety_days_ago,
                    )
                )
                .group_by(func.date(StoredConversationMetadata.created_at))
                .order_by(func.date(StoredConversationMetadata.created_at))
            )
            daily_counts_rows = daily_counts_result.all()

            # Convert to response format, filling in missing dates with 0
            daily_conversations = []
            date_counts = {
                str(row.date): row.count
                for row in daily_counts_rows
                if row.date is not None
            }

            current_date = ninety_days_ago.date()
            end_date = datetime.now(UTC).date()
            while current_date <= end_date:
                date_str = current_date.isoformat()
                daily_conversations.append(
                    DailyConversationCount(
                        date=date_str,
                        count=date_counts.get(date_str, 0),
                    )
                )
                current_date += timedelta(days=1)

        logger.info(
            "Successfully retrieved usage statistics",
            extra={
                "org_id": str(org_id),
                "total_conversations": total_conversations,
                "merged_prs": merged_prs,
                "average_cost": average_cost,
            },
        )

        return UsageStatsResponse(
            total_conversations=total_conversations,
            merged_prs=merged_prs,
            average_cost=round(average_cost, 4),
            daily_conversations=daily_conversations,
        )

    except Exception as e:
        logger.exception(
            "Error fetching usage statistics",
            extra={"org_id": str(org_id), "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics",
        )
