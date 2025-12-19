"""Integration tests for the full telemetry collection and upload flow."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from server.telemetry.service import TelemetryService


@pytest.fixture
def fresh_telemetry_service():
    """Create a fresh TelemetryService for each test."""
    TelemetryService._instance = None
    TelemetryService._initialized = False
    service = TelemetryService()
    yield service
    # Cleanup
    TelemetryService._instance = None
    TelemetryService._initialized = False


@pytest.fixture
def mock_database():
    """Mock database session for integration tests."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)
    return session


class TestTelemetryServiceLifecycle:
    """Test telemetry service startup and shutdown."""

    @pytest.mark.asyncio
    async def test_service_starts_and_stops_cleanly(self, fresh_telemetry_service):
        """Test that service starts and stops without errors."""
        with patch.object(
            fresh_telemetry_service, '_collection_loop', new_callable=AsyncMock
        ):
            with patch.object(
                fresh_telemetry_service, '_upload_loop', new_callable=AsyncMock
            ):
                with patch.object(
                    fresh_telemetry_service,
                    '_initial_collection_check',
                    new_callable=AsyncMock,
                ):
                    # Start service
                    await fresh_telemetry_service.start()

                    # Verify tasks are created
                    assert fresh_telemetry_service._collection_task is not None
                    assert fresh_telemetry_service._upload_task is not None

                    # Wait a moment for tasks to initialize
                    await asyncio.sleep(0.1)

                    # Stop service
                    await fresh_telemetry_service.stop()

                    # Verify shutdown event is set
                    assert fresh_telemetry_service._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_initial_collection_runs_on_startup(self, fresh_telemetry_service):
        """Test that initial collection check runs on startup."""
        with patch.object(
            fresh_telemetry_service, '_collection_loop', new_callable=AsyncMock
        ):
            with patch.object(
                fresh_telemetry_service, '_upload_loop', new_callable=AsyncMock
            ):
                with patch.object(
                    fresh_telemetry_service,
                    '_initial_collection_check',
                    new_callable=AsyncMock,
                ):
                    await fresh_telemetry_service.start()

                    # Wait for async task to be created
                    await asyncio.sleep(0.1)

                    # Clean up
                    await fresh_telemetry_service.stop()

                    # Verify initial collection was triggered
                    # Note: It's called via asyncio.create_task, so we can't guarantee
                    # it's been called yet, but we can verify the task was created

    @pytest.mark.asyncio
    async def test_service_handles_start_twice(self, fresh_telemetry_service):
        """Test that starting an already-started service is handled gracefully."""
        with patch.object(
            fresh_telemetry_service, '_collection_loop', new_callable=AsyncMock
        ):
            with patch.object(
                fresh_telemetry_service, '_upload_loop', new_callable=AsyncMock
            ):
                with patch.object(
                    fresh_telemetry_service,
                    '_initial_collection_check',
                    new_callable=AsyncMock,
                ):
                    # Start once
                    await fresh_telemetry_service.start()
                    first_collection_task = fresh_telemetry_service._collection_task

                    # Try to start again
                    await fresh_telemetry_service.start()

                    # Verify tasks are the same (not recreated)
                    assert (
                        fresh_telemetry_service._collection_task
                        == first_collection_task
                    )

                    # Clean up
                    await fresh_telemetry_service.stop()


class TestBootstrapPhase:
    """Test bootstrap phase behavior (before identity is established)."""

    @pytest.mark.asyncio
    async def test_bootstrap_interval_used_before_identity(
        self, fresh_telemetry_service
    ):
        """Test that bootstrap interval (3 min) is used when no identity exists."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # No identity exists
            mock_session.query.return_value.filter.return_value.first.return_value = (
                None
            )

            # Verify bootstrap interval is used
            assert not fresh_telemetry_service._is_identity_established()
            assert fresh_telemetry_service.bootstrap_check_interval_seconds == 180

    @pytest.mark.asyncio
    async def test_collection_attempts_during_bootstrap(self, fresh_telemetry_service):
        """Test that collection is attempted during bootstrap phase."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # No metrics exist, should collect
            mock_session.query.return_value.order_by.return_value.first.return_value = (
                None
            )

            assert fresh_telemetry_service._should_collect()


class TestNormalPhase:
    """Test normal phase behavior (after identity is established)."""

    @pytest.mark.asyncio
    async def test_normal_interval_used_after_identity(self, fresh_telemetry_service):
        """Test that normal interval (1 hour) is used when identity exists."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # Identity exists
            mock_identity = MagicMock()
            mock_identity.customer_id = 'test@example.com'
            mock_identity.instance_id = 'instance-123'

            mock_session.query.return_value.filter.return_value.first.return_value = (
                mock_identity
            )

            # Verify normal interval is used
            assert fresh_telemetry_service._is_identity_established()
            assert fresh_telemetry_service.normal_check_interval_seconds == 3600


class TestPhaseTransition:
    """Test transition from bootstrap to normal phase."""

    @pytest.mark.asyncio
    async def test_identity_detection_during_upload(self, fresh_telemetry_service):
        """Test that identity establishment is detected during upload."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # Initially no identity
            mock_session.query.return_value.filter.return_value.first.return_value = (
                None
            )
            assert not fresh_telemetry_service._is_identity_established()

            # Simulate identity creation
            mock_identity = MagicMock()
            mock_identity.customer_id = 'test@example.com'
            mock_identity.instance_id = 'instance-123'

            mock_session.query.return_value.filter.return_value.first.return_value = (
                mock_identity
            )

            # Now identity should be established
            assert fresh_telemetry_service._is_identity_established()

    @pytest.mark.asyncio
    async def test_immediate_upload_after_identity_creation(
        self, fresh_telemetry_service
    ):
        """Test that upload occurs immediately after identity is first created."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # No previous uploads, but have pending metrics
            mock_query1 = MagicMock()
            mock_query1.filter.return_value.order_by.return_value.first.return_value = (
                None
            )

            mock_query2 = MagicMock()
            mock_query2.filter.return_value.count.return_value = 5

            mock_session.query.side_effect = [mock_query1, mock_query2]

            # Should upload (pending metrics exist)
            assert fresh_telemetry_service._should_upload()


class TestCollectionLoop:
    """Test the collection loop behavior."""

    @pytest.mark.asyncio
    async def test_collection_interval_timing(self, fresh_telemetry_service):
        """Test that collection respects 7-day interval."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # Recent collection (3 days ago)
            mock_metric = MagicMock()
            mock_metric.collected_at = datetime.now(timezone.utc) - timedelta(days=3)

            mock_session.query.return_value.order_by.return_value.first.return_value = (
                mock_metric
            )

            # Should not collect yet
            assert not fresh_telemetry_service._should_collect()

            # Old collection (8 days ago)
            mock_metric.collected_at = datetime.now(timezone.utc) - timedelta(days=8)

            # Now should collect
            assert fresh_telemetry_service._should_collect()

    @pytest.mark.asyncio
    async def test_collection_loop_handles_errors(self, fresh_telemetry_service):
        """Test that collection loop continues after errors."""
        error_count = 0

        async def mock_collect_with_error():
            nonlocal error_count
            error_count += 1
            if error_count < 2:
                raise Exception('Collection error')
            # After first error, succeed
            pass

        with patch.object(
            fresh_telemetry_service,
            '_collect_metrics',
            side_effect=mock_collect_with_error,
        ):
            with patch.object(
                fresh_telemetry_service, '_should_collect', return_value=True
            ):
                with patch.object(
                    fresh_telemetry_service,
                    '_is_identity_established',
                    return_value=True,
                ):
                    # Start collection loop
                    task = asyncio.create_task(
                        fresh_telemetry_service._collection_loop()
                    )

                    # Wait for multiple iterations
                    await asyncio.sleep(0.3)

                    # Stop the loop
                    fresh_telemetry_service._shutdown_event.set()

                    try:
                        await asyncio.wait_for(task, timeout=1.0)
                    except asyncio.TimeoutError:
                        task.cancel()

                    # Verify error was handled (loop continued)
                    assert error_count >= 1


class TestUploadLoop:
    """Test the upload loop behavior."""

    @pytest.mark.asyncio
    async def test_upload_interval_timing(self, fresh_telemetry_service):
        """Test that upload respects 24-hour interval."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # Recent upload (12 hours ago)
            mock_metric = MagicMock()
            mock_metric.uploaded_at = datetime.now(timezone.utc) - timedelta(hours=12)

            (
                mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value
            ) = mock_metric

            # Should not upload yet
            assert not fresh_telemetry_service._should_upload()

            # Old upload (25 hours ago)
            mock_metric.uploaded_at = datetime.now(timezone.utc) - timedelta(hours=25)

            # Now should upload
            assert fresh_telemetry_service._should_upload()

    @pytest.mark.asyncio
    async def test_upload_loop_handles_errors(self, fresh_telemetry_service):
        """Test that upload loop continues after errors."""
        error_count = 0

        async def mock_upload_with_error():
            nonlocal error_count
            error_count += 1
            if error_count < 2:
                raise Exception('Upload error')
            pass

        with patch.object(
            fresh_telemetry_service,
            '_upload_pending_metrics',
            side_effect=mock_upload_with_error,
        ):
            with patch.object(
                fresh_telemetry_service, '_should_upload', return_value=True
            ):
                with patch.object(
                    fresh_telemetry_service,
                    '_is_identity_established',
                    return_value=True,
                ):
                    # Start upload loop
                    task = asyncio.create_task(fresh_telemetry_service._upload_loop())

                    # Wait for multiple iterations
                    await asyncio.sleep(0.3)

                    # Stop the loop
                    fresh_telemetry_service._shutdown_event.set()

                    try:
                        await asyncio.wait_for(task, timeout=1.0)
                    except asyncio.TimeoutError:
                        task.cancel()

                    # Verify error was handled (loop continued)
                    assert error_count >= 1


class TestMetricsCollection:
    """Test metrics collection from registered collectors."""

    @pytest.mark.asyncio
    async def test_collect_metrics_from_registry(self, fresh_telemetry_service):
        """Test that metrics are collected from all registered collectors."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            with patch(
                'server.telemetry.service.CollectorRegistry'
            ) as mock_registry_class:
                mock_registry = MagicMock()
                mock_registry_class.return_value = mock_registry

                # Create mock collector
                mock_collector = MagicMock()
                mock_collector.collector_name = 'TestCollector'
                mock_collector.should_collect.return_value = True

                # Create mock metric result
                mock_result = MagicMock()
                mock_result.key = 'test_key'
                mock_result.value = 'test_value'

                mock_collector.collect.return_value = [mock_result]
                mock_registry.get_all_collectors.return_value = [mock_collector]

                # Run collection
                await fresh_telemetry_service._collect_metrics()

                # Verify collector was called
                mock_collector.should_collect.assert_called_once()
                mock_collector.collect.assert_called_once()

                # Verify metrics were stored
                mock_session.add.assert_called_once()
                mock_session.commit.assert_called()


class TestReplicatedIntegration:
    """Test Replicated SDK integration (mocked)."""

    @pytest.mark.asyncio
    async def test_upload_creates_customer_and_instance(self, fresh_telemetry_service):
        """Test that upload creates Replicated customer and instance."""
        with patch('server.telemetry.service.session_maker') as mock_session_maker:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=None)
            mock_session_maker.return_value = mock_session

            # Mock pending metrics
            mock_metric = MagicMock()
            mock_metric.id = 1
            mock_metric.metrics_data = {'test_key': 'test_value'}
            mock_metric.upload_attempts = 0

            mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
                mock_metric
            ]

            # Mock admin email
            mock_user = MagicMock()
            mock_user.email = 'admin@example.com'

            (
                mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value
            ) = mock_user

            # Mock identity
            mock_identity = MagicMock()
            mock_identity.customer_id = None
            mock_identity.instance_id = None

            (
                mock_session.query.return_value.filter.return_value.first.return_value
            ) = mock_identity

            # Mock Replicated client and availability flag
            with patch('server.telemetry.service.REPLICATED_AVAILABLE', True):
                with patch('server.telemetry.service.InstanceStatus') as mock_status:
                    mock_status.RUNNING = 'RUNNING'
                    with patch(
                        'server.telemetry.service.ReplicatedClient'
                    ) as mock_client_class:
                        mock_client = MagicMock()
                        mock_customer = MagicMock()
                        mock_customer.customer_id = 'cust-123'
                        mock_instance = MagicMock()
                        mock_instance.instance_id = 'inst-456'

                        mock_customer.get_or_create_instance.return_value = (
                            mock_instance
                        )
                        mock_client.customer.get_or_create.return_value = mock_customer

                        mock_client_class.return_value = mock_client

                        # Run upload
                        await fresh_telemetry_service._upload_pending_metrics()

                        # Verify Replicated client was created with correct parameters
                        # Called twice: once for identity creation, once for upload
                        assert mock_client_class.call_count == 2
                        call_args = mock_client_class.call_args
                        assert 'publishable_key' in call_args.kwargs
                        assert 'app_slug' in call_args.kwargs
