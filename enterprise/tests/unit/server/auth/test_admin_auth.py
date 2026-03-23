"""
Unit tests for admin authentication dependency (get_admin_user_id).

Tests the FastAPI dependency that validates user has admin role.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from server.auth.admin_auth import get_admin_user_id


@pytest.fixture
def mock_user():
    """Create a mock User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


@pytest.fixture
def mock_admin_role():
    """Create a mock admin Role object."""
    role = MagicMock()
    role.name = 'admin'
    return role


@pytest.fixture
def mock_user_role():
    """Create a mock regular user Role object."""
    role = MagicMock()
    role.name = 'user'
    return role


@pytest.fixture
def mock_owner_role():
    """Create a mock owner Role object."""
    role = MagicMock()
    role.name = 'owner'
    return role


@pytest.mark.asyncio
async def test_get_admin_user_id_success(mock_user, mock_admin_role):
    """
    GIVEN: Valid user ID and user has admin role
    WHEN: get_admin_user_id is called
    THEN: User ID is returned successfully
    """
    # Arrange
    user_id = str(uuid.uuid4())
    mock_user.role = mock_admin_role

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch('server.auth.admin_auth.a_session_maker', return_value=mock_session):
        # Act
        result = await get_admin_user_id(user_id)

        # Assert
        assert result == user_id


@pytest.mark.asyncio
async def test_get_admin_user_id_no_user_id():
    """
    GIVEN: No user ID provided (None)
    WHEN: get_admin_user_id is called
    THEN: 401 Unauthorized is raised
    """
    # Arrange
    user_id = None

    # Act & Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_admin_user_id(user_id)

    assert exc_info.value.status_code == 401
    assert 'not authenticated' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_empty_string_user_id():
    """
    GIVEN: Empty string user ID
    WHEN: get_admin_user_id is called
    THEN: 401 Unauthorized is raised
    """
    # Arrange
    user_id = ''

    # Act & Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_admin_user_id(user_id)

    assert exc_info.value.status_code == 401
    assert 'not authenticated' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_user_not_found():
    """
    GIVEN: User ID provided but user does not exist in database
    WHEN: get_admin_user_id is called
    THEN: 403 Forbidden is raised
    """
    # Arrange
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch('server.auth.admin_auth.a_session_maker', return_value=mock_session):
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user_id(user_id)

        assert exc_info.value.status_code == 403
        assert 'admin' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_user_no_role(mock_user):
    """
    GIVEN: User ID and user has no role assigned
    WHEN: get_admin_user_id is called
    THEN: 403 Forbidden is raised
    """
    # Arrange
    user_id = str(uuid.uuid4())
    mock_user.role = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch('server.auth.admin_auth.a_session_maker', return_value=mock_session):
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user_id(user_id)

        assert exc_info.value.status_code == 403
        assert 'admin' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_user_is_regular_user(mock_user, mock_user_role):
    """
    GIVEN: User ID and user has 'user' role (not admin)
    WHEN: get_admin_user_id is called
    THEN: 403 Forbidden is raised
    """
    # Arrange
    user_id = str(uuid.uuid4())
    mock_user.role = mock_user_role

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch('server.auth.admin_auth.a_session_maker', return_value=mock_session):
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user_id(user_id)

        assert exc_info.value.status_code == 403
        assert 'admin' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_user_is_owner(mock_user, mock_owner_role):
    """
    GIVEN: User ID and user has 'owner' role (not admin)
    WHEN: get_admin_user_id is called
    THEN: 403 Forbidden is raised (owner is not admin)
    """
    # Arrange
    user_id = str(uuid.uuid4())
    mock_user.role = mock_owner_role

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch('server.auth.admin_auth.a_session_maker', return_value=mock_session):
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user_id(user_id)

        assert exc_info.value.status_code == 403
        assert 'admin' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_admin_user_id_logs_warning_on_non_admin(mock_user, mock_user_role):
    """
    GIVEN: User with non-admin role
    WHEN: get_admin_user_id is called
    THEN: Warning is logged with user_id and role
    """
    # Arrange
    user_id = str(uuid.uuid4())
    mock_user.role = mock_user_role

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch('server.auth.admin_auth.a_session_maker', return_value=mock_session),
        patch('server.auth.admin_auth.logger') as mock_logger,
    ):
        # Act & Assert
        with pytest.raises(HTTPException):
            await get_admin_user_id(user_id)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert 'not an admin' in call_args[0][0]
        assert call_args[1]['extra']['user_id'] == user_id
        assert call_args[1]['extra']['role'] == 'user'


@pytest.mark.asyncio
async def test_get_admin_user_id_logs_warning_on_user_not_found():
    """
    GIVEN: User that does not exist in database
    WHEN: get_admin_user_id is called
    THEN: Warning is logged indicating user not found
    """
    # Arrange
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch('server.auth.admin_auth.a_session_maker', return_value=mock_session),
        patch('server.auth.admin_auth.logger') as mock_logger,
    ):
        # Act & Assert
        with pytest.raises(HTTPException):
            await get_admin_user_id(user_id)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert 'user not found' in call_args[0][0]
        assert call_args[1]['extra']['user_id'] == user_id
