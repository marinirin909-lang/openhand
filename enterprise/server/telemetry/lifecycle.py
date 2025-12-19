"""FastAPI lifespan integration for the embedded telemetry service."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from server.logger import logger
from server.telemetry.service import telemetry_service


@asynccontextmanager
async def telemetry_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context manager for telemetry service.

    This is called automatically during FastAPI application startup and shutdown,
    managing the lifecycle of the telemetry background tasks.

    Startup: Initializes and starts background collection and upload tasks
    Shutdown: Gracefully stops background tasks
    """
    logger.info('Starting telemetry service lifespan')

    # Startup - start background tasks
    try:
        await telemetry_service.start()
        logger.info('Telemetry service started successfully')
    except Exception as e:
        logger.error(f'Error starting telemetry service: {e}', exc_info=True)
        # Don't fail server startup if telemetry fails

    yield  # Server runs here

    # Shutdown - stop background tasks
    try:
        await telemetry_service.stop()
        logger.info('Telemetry service stopped successfully')
    except Exception as e:
        logger.error(f'Error stopping telemetry service: {e}', exc_info=True)
