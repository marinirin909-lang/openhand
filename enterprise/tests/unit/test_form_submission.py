"""Unit tests for form submission API."""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from server.auth.saas_user_auth import SaasUserAuth
from server.routes.form_submission import (
    FormSubmissionRequest,
    FormSubmissionResponse,
    _validate_and_sanitize_enterprise_lead_answers,
    submit_form,
)
from sqlalchemy import select
from storage.form_submission import FormSubmission


@pytest.fixture
def valid_enterprise_lead_data():
    """Valid enterprise lead form data."""
    return {
        'form_type': 'enterprise_lead',
        'answers': {
            'request_type': 'saas',
            'name': 'John Doe',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
            'message': 'We are interested in your enterprise plan.',
        },
    }


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.state = MagicMock()
    request.state.user_auth = None  # Unauthenticated request
    return request


@pytest.fixture
def mock_authenticated_request():
    """Create a mock authenticated FastAPI request."""
    request = MagicMock()
    mock_user_auth = MagicMock(spec=SaasUserAuth)
    mock_user_auth.user_id = str(uuid4())
    request.state.user_auth = mock_user_auth
    return request


class TestEnterpriseLeadValidation:
    """Tests for enterprise lead form validation."""

    def test_valid_saas_request_type(self):
        """Test validation passes for saas request type."""
        answers = {
            'request_type': 'saas',
            'name': 'John Doe',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
            'message': 'Interested in saas.',
        }
        # Should not raise
        _validate_and_sanitize_enterprise_lead_answers(answers)

    def test_valid_self_hosted_request_type(self):
        """Test validation passes for self-hosted request type."""
        answers = {
            'request_type': 'self-hosted',
            'name': 'Jane Smith',
            'company': 'Tech Inc',
            'email': 'jane@tech.com',
            'message': 'Need self-hosted solution.',
        }
        # Should not raise
        _validate_and_sanitize_enterprise_lead_answers(answers)

    def test_invalid_request_type(self):
        """Test validation fails for invalid request type."""
        answers = {
            'request_type': 'invalid',
            'name': 'John Doe',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
            'message': 'Test message.',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400
        assert 'Invalid enterprise lead form answers' in excinfo.value.detail

    def test_missing_name(self):
        """Test validation fails when name is missing."""
        answers = {
            'request_type': 'saas',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
            'message': 'Test message.',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400

    def test_empty_name(self):
        """Test validation fails when name is empty."""
        answers = {
            'request_type': 'saas',
            'name': '',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
            'message': 'Test message.',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400

    def test_missing_email(self):
        """Test validation fails when email is missing."""
        answers = {
            'request_type': 'saas',
            'name': 'John Doe',
            'company': 'Acme Corp',
            'message': 'Test message.',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400

    def test_missing_company(self):
        """Test validation fails when company is missing."""
        answers = {
            'request_type': 'saas',
            'name': 'John Doe',
            'email': 'john@acme.com',
            'message': 'Test message.',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400

    def test_missing_message(self):
        """Test validation fails when message is missing."""
        answers = {
            'request_type': 'saas',
            'name': 'John Doe',
            'company': 'Acme Corp',
            'email': 'john@acme.com',
        }
        with pytest.raises(HTTPException) as excinfo:
            _validate_and_sanitize_enterprise_lead_answers(answers)
        assert excinfo.value.status_code == 400


class TestSubmitForm:
    """Tests for form submission endpoint."""

    @pytest.mark.asyncio
    async def test_submit_enterprise_lead_unauthenticated(
        self, valid_enterprise_lead_data, mock_request, async_session_maker
    ):
        """Test submitting enterprise lead form without authentication."""
        submission_request = FormSubmissionRequest(**valid_enterprise_lead_data)

        with patch(
            'server.routes.form_submission.a_session_maker', async_session_maker
        ):
            result = await submit_form(mock_request, submission_request)

        # Verify response type
        assert isinstance(result, FormSubmissionResponse)
        assert result.status == 'pending'
        assert result.created_at is not None

        # Verify the submission was persisted in the database
        async with async_session_maker() as session:
            db_result = await session.execute(
                select(FormSubmission).filter(FormSubmission.id == UUID(result.id))
            )
            submission = db_result.scalars().first()
            assert submission is not None
            assert submission.form_type == 'enterprise_lead'
            assert submission.answers == valid_enterprise_lead_data['answers']
            assert submission.status == 'pending'
            assert submission.user_id is None  # Unauthenticated

    @pytest.mark.asyncio
    async def test_submit_enterprise_lead_authenticated(
        self,
        valid_enterprise_lead_data,
        mock_authenticated_request,
        async_session_maker,
    ):
        """Test submitting enterprise lead form with authentication."""
        submission_request = FormSubmissionRequest(**valid_enterprise_lead_data)
        expected_user_id = mock_authenticated_request.state.user_auth.user_id

        with patch(
            'server.routes.form_submission.a_session_maker', async_session_maker
        ):
            result = await submit_form(mock_authenticated_request, submission_request)

        # Verify response type
        assert isinstance(result, FormSubmissionResponse)

        # Verify the submission was persisted with user_id
        async with async_session_maker() as session:
            db_result = await session.execute(
                select(FormSubmission).filter(FormSubmission.id == UUID(result.id))
            )
            submission = db_result.scalars().first()
            assert submission is not None
            assert submission.user_id == UUID(expected_user_id)

    @pytest.mark.asyncio
    async def test_submit_invalid_form_type(self, mock_request, async_session_maker):
        """Test submitting with invalid form type."""
        submission_request = FormSubmissionRequest(
            form_type='invalid_type',
            answers={'key': 'value'},
        )

        with patch(
            'server.routes.form_submission.a_session_maker', async_session_maker
        ):
            with pytest.raises(HTTPException) as excinfo:
                await submit_form(mock_request, submission_request)

        assert excinfo.value.status_code == 400
        assert 'Invalid form_type' in excinfo.value.detail

    @pytest.mark.asyncio
    async def test_submit_self_hosted_request_type(
        self, mock_request, async_session_maker
    ):
        """Test submitting with self-hosted request type."""
        submission_request = FormSubmissionRequest(
            form_type='enterprise_lead',
            answers={
                'request_type': 'self-hosted',
                'name': 'Test User',
                'company': 'Test Company',
                'email': 'test@example.com',
                'message': 'Need self-hosted solution.',
            },
        )

        with patch(
            'server.routes.form_submission.a_session_maker', async_session_maker
        ):
            result = await submit_form(mock_request, submission_request)

        assert isinstance(result, FormSubmissionResponse)

        # Verify the submission was persisted with correct request_type
        async with async_session_maker() as session:
            db_result = await session.execute(
                select(FormSubmission).filter(FormSubmission.id == UUID(result.id))
            )
            submission = db_result.scalars().first()
            assert submission is not None
            assert submission.answers['request_type'] == 'self-hosted'

    @pytest.mark.asyncio
    async def test_rate_limit_enforced(
        self, valid_enterprise_lead_data, mock_request, async_session_maker
    ):
        """Test that rate limiting is enforced and returns 429."""
        from server.rate_limit import RateLimitException, RateLimitResult

        submission_request = FormSubmissionRequest(**valid_enterprise_lead_data)

        # Mock rate limiter to raise RateLimitException (simulating limit hit)
        rate_limit_result = RateLimitResult(
            description='5 per 1 hour',
            remaining=0,
            reset_time=3600,
            retry_after=3600,
        )

        with (
            patch('server.routes.form_submission.a_session_maker', async_session_maker),
            patch(
                'server.routes.form_submission.form_submit_rate_limiter.hit',
                side_effect=RateLimitException(rate_limit_result),
            ),
        ):
            with pytest.raises(RateLimitException) as excinfo:
                await submit_form(mock_request, submission_request)

            assert excinfo.value.status_code == 429
            assert '5 per 1 hour' in excinfo.value.detail

    @pytest.mark.asyncio
    async def test_invalid_user_id_returns_500(
        self, valid_enterprise_lead_data, async_session_maker
    ):
        """Test that malformed user_id from auth returns 500 (fail-fast behavior)."""
        submission_request = FormSubmissionRequest(**valid_enterprise_lead_data)

        # Create mock request with invalid UUID in user_auth
        request = MagicMock()
        mock_user_auth = MagicMock(spec=SaasUserAuth)
        mock_user_auth.user_id = 'not-a-valid-uuid'  # Invalid UUID format
        request.state.user_auth = mock_user_auth

        with patch(
            'server.routes.form_submission.a_session_maker', async_session_maker
        ):
            with pytest.raises(HTTPException) as excinfo:
                await submit_form(request, submission_request)

            # Should return 500 (not 400) to surface auth system bug
            assert excinfo.value.status_code == 500
            assert 'Internal authentication error' in excinfo.value.detail


class TestFormSubmissionRequest:
    """Tests for the Pydantic request model."""

    def test_valid_request(self, valid_enterprise_lead_data):
        """Test creating a valid request."""
        request = FormSubmissionRequest(**valid_enterprise_lead_data)
        assert request.form_type == 'enterprise_lead'
        assert request.answers == valid_enterprise_lead_data['answers']

    def test_form_type_max_length(self):
        """Test form_type max length validation."""
        with pytest.raises(ValidationError):
            FormSubmissionRequest(
                form_type='a' * 51,  # Over 50 chars
                answers={'key': 'value'},
            )
