"""Onboarding submission endpoint.

Receives user onboarding selections and fires analytics event.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from openhands.server.user_auth import get_user_id

onboarding_router = APIRouter(prefix='/api', tags=['Onboarding'])


class OnboardingSubmission(BaseModel):
    selections: dict[
        str, str
    ]  # step_id -> option_id (e.g., {"step1": "software_engineer", "step2": "solo", "step3": "new_features"})


class OnboardingResponse(BaseModel):
    status: str
    redirect_url: str


@onboarding_router.post('/onboarding', response_model=OnboardingResponse)
async def submit_onboarding(
    body: OnboardingSubmission,
    user_id: str | None = Depends(get_user_id),
) -> OnboardingResponse:
    """Submit onboarding form selections and fire analytics event."""
    # ACTV-03: onboarding completed
    try:
        from openhands.analytics import get_analytics_service, resolve_context

        analytics = get_analytics_service()
        if analytics and user_id:
            ctx = await resolve_context(user_id)

            analytics.track_onboarding_completed(
                distinct_id=user_id,
                role=body.selections.get('step1'),
                org_size=body.selections.get('step2'),
                use_case=body.selections.get('step3'),
                org_id=ctx.org_id,
                consented=ctx.consented,
            )

            # Associate onboarding timestamp with org group
            if ctx.org_id:
                analytics.group_identify(
                    group_type='org',
                    group_key=ctx.org_id,
                    properties={
                        'onboarding_completed_at': datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    distinct_id=user_id,
                    consented=ctx.consented,
                )
    except Exception:
        import logging

        logging.getLogger(__name__).exception('analytics:onboarding_completed:failed')

    return OnboardingResponse(status='ok', redirect_url='/')
