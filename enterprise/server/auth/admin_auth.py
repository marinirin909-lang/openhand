"""
Admin authentication utilities for enterprise endpoints.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import selectinload

from openhands.core.logger import openhands_logger as logger
from openhands.server.user_auth import get_user_id

from storage.database import a_session_maker
from storage.user import User


async def get_admin_user_id(user_id: str | None = Depends(get_user_id)) -> str:
    """
    Dependency that validates user has the admin role.

    This dependency can be used in place of get_user_id for endpoints that
    should only be accessible to admin users. The admin role is checked
    against the User table's role relationship.

    Args:
        user_id: User ID from get_user_id dependency

    Returns:
        str: User ID if user has admin role

    Raises:
        HTTPException: 403 if user does not have admin role
        HTTPException: 401 if user is not authenticated

    Example:
        @router.post('/endpoint')
        async def create_resource(
            user_id: str = Depends(get_admin_user_id),
        ):
            # Only admin users can access this endpoint
            pass
    """
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='User not authenticated',
        )

    async with a_session_maker() as session:
        from sqlalchemy import select
        import uuid

        result = await session.execute(
            select(User)
            .options(selectinload(User.role))
            .filter(User.id == uuid.UUID(user_id))
        )
        user = result.scalars().first()

        if not user:
            logger.warning(
                'Access denied - user not found',
                extra={'user_id': user_id},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Access restricted to admin users',
            )

        if not user.role or user.role.name != 'admin':
            logger.warning(
                'Access denied - user is not an admin',
                extra={'user_id': user_id, 'role': user.role.name if user.role else None},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Access restricted to admin users',
            )

    return user_id
