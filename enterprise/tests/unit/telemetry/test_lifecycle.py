"""Unit tests for the telemetry lifespan integration."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from server.telemetry.lifecycle import telemetry_lifespan


@pytest.fixture
def mock_app():
    """Create a mock FastAPI application."""
    return FastAPI()


class TestTelemetryLifespan:
    """Test telemetry lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_normal_operation(self, mock_app):
        """Test normal lifespan operation with successful start and stop."""
        with patch(
            'server.telemetry.lifecycle.telemetry_service'
        ) as mock_telemetry_service:
            mock_telemetry_service.start = AsyncMock()
            mock_telemetry_service.stop = AsyncMock()

            async with telemetry_lifespan(mock_app):
                # During lifespan, service should be started
                mock_telemetry_service.start.assert_called_once()
                assert not mock_telemetry_service.stop.called

            # After lifespan, service should be stopped
            mock_telemetry_service.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_start_error(self, mock_app):
        """Test that start errors don't prevent server from starting."""
        with patch(
            'server.telemetry.lifecycle.telemetry_service'
        ) as mock_telemetry_service:
            mock_telemetry_service.start = AsyncMock(
                side_effect=Exception('Start failed')
            )
            mock_telemetry_service.stop = AsyncMock()

            # Should not raise exception
            async with telemetry_lifespan(mock_app):
                mock_telemetry_service.start.assert_called_once()

            # Stop should still be called
            mock_telemetry_service.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_stop_error(self, mock_app):
        """Test that stop errors don't prevent server shutdown."""
        with patch(
            'server.telemetry.lifecycle.telemetry_service'
        ) as mock_telemetry_service:
            mock_telemetry_service.start = AsyncMock()
            mock_telemetry_service.stop = AsyncMock(
                side_effect=Exception('Stop failed')
            )

            # Should not raise exception
            async with telemetry_lifespan(mock_app):
                pass

            mock_telemetry_service.start.assert_called_once()
            mock_telemetry_service.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_server_run_phase(self, mock_app):
        """Test that server runs between start and stop."""
        with patch(
            'server.telemetry.lifecycle.telemetry_service'
        ) as mock_telemetry_service:
            mock_telemetry_service.start = AsyncMock()
            mock_telemetry_service.stop = AsyncMock()

            server_ran = False

            async with telemetry_lifespan(mock_app):
                # Verify start was called before yield
                mock_telemetry_service.start.assert_called_once()
                # Verify stop has not been called yet
                assert not mock_telemetry_service.stop.called
                server_ran = True

            # Verify the server phase executed
            assert server_ran
            # Verify stop was called after yield
            mock_telemetry_service.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_logging(self, mock_app):
        """Test that lifecycle events are logged."""
        with patch(
            'server.telemetry.lifecycle.telemetry_service'
        ) as mock_telemetry_service:
            mock_telemetry_service.start = AsyncMock()
            mock_telemetry_service.stop = AsyncMock()

            with patch('server.telemetry.lifecycle.logger') as mock_logger:
                async with telemetry_lifespan(mock_app):
                    pass

                # Check that lifecycle events were logged
                assert mock_logger.info.call_count >= 2  # At least start and stop logs
