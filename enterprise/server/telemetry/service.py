"""Embedded telemetry service that runs as part of the enterprise server process."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from server.logger import logger
from storage.database import session_maker
from storage.telemetry_identity import TelemetryIdentity
from storage.telemetry_metrics import TelemetryMetrics
from storage.user_settings import UserSettings
from telemetry.registry import CollectorRegistry

# Optional import for Replicated SDK (to be implemented in M4)
try:
    from replicated import InstanceStatus, ReplicatedClient

    REPLICATED_AVAILABLE = True
except ImportError:
    REPLICATED_AVAILABLE = False
    InstanceStatus = None  # type: ignore
    ReplicatedClient = None  # type: ignore


class TelemetryService:
    """Singleton service for managing embedded telemetry collection and upload.

    This service runs as part of the main enterprise server process using AsyncIO
    background tasks. It starts automatically during FastAPI application startup
    and runs independently without requiring external CronJobs or maintenance workers.

    Two-Phase Scheduling:
    ---------------------
    The service uses adaptive scheduling to minimize time-to-visibility for new installations:

    Phase 1 (Bootstrap - No Identity Established):
    - Runs when no user has authenticated yet (no admin email available)
    - Checks every 3 minutes for first user authentication
    - Immediately collects and uploads metrics once first user authenticates
    - Creates Replicated customer and instance identity on first upload

    Phase 2 (Normal Operations - Identity Established):
    - Runs after identity (customer_id + instance_id) is created
    - Checks every hour (reduced overhead)
    - Collects metrics every 7 days
    - Uploads metrics every 24 hours

    This ensures new installations become visible to the vendor within minutes of first use,
    while established installations maintain low resource overhead.
    """

    _instance: Optional['TelemetryService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._collection_task: Optional[asyncio.Task] = None
        self._upload_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Configuration (from environment or defaults)
        self.collection_interval_days = int(
            os.getenv('TELEMETRY_COLLECTION_INTERVAL_DAYS', '7')
        )
        self.upload_interval_hours = int(
            os.getenv('TELEMETRY_UPLOAD_INTERVAL_HOURS', '24')
        )
        self.license_warning_threshold_days = int(
            os.getenv('TELEMETRY_WARNING_THRESHOLD_DAYS', '4')
        )

        # Two-phase scheduling: Before identity is established, check more frequently
        # Phase 1 (no identity): Check every 3 minutes for first user authentication
        # Phase 2 (identity exists): Check every hour for normal operations
        self.bootstrap_check_interval_seconds = 180  # 3 minutes
        self.normal_check_interval_seconds = 3600  # 1 hour

        # Replicated API configuration - HARDCODED for security through obscurity
        # This publishable key (replicated_pk_...) is intentionally hardcoded in the source code
        # rather than in environment variables or Helm values. This makes the telemetry system:
        # 1. Harder to detect (requires source code inspection)
        # 2. Harder to disable (requires code modification and rebuild)
        # 3. Harder to tamper with (can't just change an env var)
        #
        # The publishable key is safe to hardcode because:
        # - It's vendor-wide, shared across ALL customer deployments
        # - It only has write privileges for metrics (cannot read other customers' data)
        # - Individual customers are identified by email, not by this API key
        # - This is the same security model as Stripe's frontend publishable keys
        self.replicated_publishable_key = (
            'replicated_pk_xxxxxxxxxxxxxxxxxxxxxxxxxx'  # TODO: Replace with actual key
        )
        self.replicated_app_slug = 'openhands-enterprise'

        logger.info('TelemetryService initialized')

    async def start(self):
        """Start the telemetry service background tasks.

        Called automatically during FastAPI application startup via lifespan events.
        """
        if self._collection_task is not None or self._upload_task is not None:
            logger.warning('TelemetryService already started')
            return

        logger.info('Starting TelemetryService background tasks')

        # Start independent background loops
        self._collection_task = asyncio.create_task(self._collection_loop())
        self._upload_task = asyncio.create_task(self._upload_loop())

        # Run initial collection if needed (don't wait for 7-day interval)
        asyncio.create_task(self._initial_collection_check())

    async def stop(self):
        """Stop the telemetry service and perform cleanup.

        Called automatically during FastAPI application shutdown via lifespan events.
        """
        logger.info('Stopping TelemetryService')

        self._shutdown_event.set()

        # Cancel background tasks
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass

        if self._upload_task:
            self._upload_task.cancel()
            try:
                await self._upload_task
            except asyncio.CancelledError:
                pass

        logger.info('TelemetryService stopped')

    async def _collection_loop(self):
        """Background task that checks if metrics collection is needed.

        Uses two-phase scheduling:
        - Phase 1 (bootstrap): Checks every 3 minutes until identity is established
        - Phase 2 (normal): Checks every hour, collects every 7 days

        This ensures rapid first collection after user authentication while maintaining
        low overhead for ongoing operations.
        """
        logger.info(
            f'Collection loop started (interval: {self.collection_interval_days} days)'
        )

        while not self._shutdown_event.is_set():
            try:
                # Determine check interval based on whether identity is established
                identity_established = self._is_identity_established()
                check_interval = (
                    self.normal_check_interval_seconds
                    if identity_established
                    else self.bootstrap_check_interval_seconds
                )

                if not identity_established:
                    logger.debug(
                        'Identity not yet established, using bootstrap interval (3 minutes)'
                    )

                # Check if collection is needed
                if self._should_collect():
                    logger.info('Starting metrics collection')
                    await self._collect_metrics()
                    logger.info('Metrics collection completed')

                # Sleep until next check (interval depends on phase)
                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info('Collection loop cancelled')
                break
            except Exception as e:
                logger.error(f'Error in collection loop: {e}', exc_info=True)
                # Continue running even if collection fails
                # Use shorter interval on error to retry sooner
                await asyncio.sleep(self.bootstrap_check_interval_seconds)

    async def _upload_loop(self):
        """Background task that checks if metrics upload is needed.

        Uses two-phase scheduling:
        - Phase 1 (bootstrap): Checks every 3 minutes for first user, uploads immediately
        - Phase 2 (normal): Checks every hour, uploads every 24 hours

        When identity is first established, triggers immediate upload to minimize time
        until vendor visibility. After that, follows normal 24-hour upload schedule.
        """
        logger.info(
            f'Upload loop started (interval: {self.upload_interval_hours} hours)'
        )

        while not self._shutdown_event.is_set():
            try:
                # Determine check interval based on whether identity is established
                identity_established = self._is_identity_established()
                check_interval = (
                    self.normal_check_interval_seconds
                    if identity_established
                    else self.bootstrap_check_interval_seconds
                )

                if not identity_established:
                    logger.debug(
                        'Identity not yet established, using bootstrap interval (3 minutes)'
                    )

                # Check if upload is needed
                # In bootstrap phase, attempt upload whenever there are pending metrics
                # (upload will be skipped internally if no admin email available)
                if self._should_upload():
                    logger.info('Starting metrics upload')
                    was_established_before = identity_established
                    await self._upload_pending_metrics()

                    # If identity was just established, it will be created during upload
                    # Continue with short interval for one more cycle to ensure upload succeeds
                    if not was_established_before and self._is_identity_established():
                        logger.info(
                            'Identity just established - first upload completed'
                        )

                    logger.info('Metrics upload completed')

                # Sleep until next check (interval depends on phase)
                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info('Upload loop cancelled')
                break
            except Exception as e:
                logger.error(f'Error in upload loop: {e}', exc_info=True)
                # Continue running even if upload fails
                # Use shorter interval on error to retry sooner
                await asyncio.sleep(self.bootstrap_check_interval_seconds)

    async def _initial_collection_check(self):
        """Check on startup if initial collection is needed."""
        try:
            with session_maker() as session:
                count = session.query(TelemetryMetrics).count()
                if count == 0:
                    logger.info('No existing metrics found, running initial collection')
                    await self._collect_metrics()
        except Exception as e:
            logger.error(f'Error during initial collection check: {e}')

    def _is_identity_established(self) -> bool:
        """Check if telemetry identity has been established.

        Returns True if we have both customer_id and instance_id in the database,
        indicating that at least one user has authenticated and we can send telemetry.
        """
        try:
            with session_maker() as session:
                identity = (
                    session.query(TelemetryIdentity)
                    .filter(TelemetryIdentity.id == 1)
                    .first()
                )

                # Identity is established if we have both customer_id and instance_id
                return (
                    identity is not None
                    and identity.customer_id is not None
                    and identity.instance_id is not None
                )
        except Exception as e:
            logger.error(f'Error checking identity status: {e}')
            return False

    def _should_collect(self) -> bool:
        """Check if 7 days have passed since last collection."""
        try:
            with session_maker() as session:
                last_metric = (
                    session.query(TelemetryMetrics)
                    .order_by(TelemetryMetrics.collected_at.desc())
                    .first()
                )

                if not last_metric:
                    return True  # First collection

                days_since = (
                    datetime.now(timezone.utc) - last_metric.collected_at
                ).days
                return days_since >= self.collection_interval_days
        except Exception as e:
            logger.error(f'Error checking collection status: {e}')
            return False

    def _should_upload(self) -> bool:
        """Check if 24 hours have passed since last upload."""
        try:
            with session_maker() as session:
                last_uploaded = (
                    session.query(TelemetryMetrics)
                    .filter(TelemetryMetrics.uploaded_at.isnot(None))
                    .order_by(TelemetryMetrics.uploaded_at.desc())
                    .first()
                )

                if not last_uploaded:
                    # Check if we have any pending metrics to upload
                    pending_count = (
                        session.query(TelemetryMetrics)
                        .filter(TelemetryMetrics.uploaded_at.is_(None))
                        .count()
                    )
                    return pending_count > 0

                hours_since = (
                    datetime.now(timezone.utc) - last_uploaded.uploaded_at
                ).total_seconds() / 3600
                return hours_since >= self.upload_interval_hours
        except Exception as e:
            logger.error(f'Error checking upload status: {e}')
            return False

    async def _collect_metrics(self):
        """Collect metrics from all registered collectors and store in database."""
        try:
            # Get all registered collectors
            registry = CollectorRegistry()
            collectors = registry.get_all_collectors()

            # Collect metrics from each collector
            all_metrics = {}
            collector_results = {}

            for collector in collectors:
                try:
                    if collector.should_collect():
                        results = collector.collect()
                        for result in results:
                            all_metrics[result.key] = result.value
                        collector_results[collector.collector_name] = len(results)
                        logger.info(
                            f'Collected {len(results)} metrics from {collector.collector_name}'
                        )
                except Exception as e:
                    logger.error(
                        f'Collector {collector.collector_name} failed: {e}',
                        exc_info=True,
                    )
                    collector_results[collector.collector_name] = 0

            # Store metrics in database
            with session_maker() as session:
                telemetry_record = TelemetryMetrics(
                    metrics_data=all_metrics, collected_at=datetime.now(timezone.utc)
                )
                session.add(telemetry_record)
                session.commit()

                logger.info(f'Stored {len(all_metrics)} metrics in database')

        except Exception as e:
            logger.error(f'Error during metrics collection: {e}', exc_info=True)

    async def _upload_pending_metrics(self):
        """Upload pending metrics to Replicated."""
        if not REPLICATED_AVAILABLE:
            logger.warning('Replicated SDK not available, skipping upload')
            return

        if not self.replicated_publishable_key:
            logger.warning('REPLICATED_PUBLISHABLE_KEY not set, skipping upload')
            return

        try:
            # Get pending metrics
            with session_maker() as session:
                pending_metrics = (
                    session.query(TelemetryMetrics)
                    .filter(TelemetryMetrics.uploaded_at.is_(None))
                    .order_by(TelemetryMetrics.collected_at)
                    .all()
                )

                if not pending_metrics:
                    logger.info('No pending metrics to upload')
                    return

                # Get admin email - skip if not available
                admin_email = self._get_admin_email(session)
                if not admin_email:
                    logger.warning('No admin email available, skipping upload')
                    return

                # Get or create identity
                identity = self._get_or_create_identity(session, admin_email)

                # Initialize Replicated client with publishable key
                # This publishable key is intentionally embedded in the application and shared
                # across all customer deployments. It's safe to use here because:
                # 1. It only has write privileges for metrics (cannot read other customers' data)
                # 2. It identifies the vendor (OpenHands), not individual customers
                # 3. Customer identification happens via email address passed to get_or_create()
                client = ReplicatedClient(
                    publishable_key=self.replicated_publishable_key,
                    app_slug=self.replicated_app_slug,
                )

                # Upload each pending metric
                successful_count = 0
                # Get or create customer and instance
                customer = client.customer.get_or_create(email_address=admin_email)
                instance = customer.get_or_create_instance()

                # Update identity with Replicated IDs
                identity.customer_id = customer.customer_id
                identity.instance_id = instance.instance_id
                session.commit()

                # Upload each pending metric
                for metric in pending_metrics:
                    try:
                        # Send individual metrics
                        for key, value in metric.metrics_data.items():
                            instance.send_metric(key, value)

                        # Update instance status
                        instance.set_status(InstanceStatus.RUNNING)

                        # Mark as uploaded
                        metric.uploaded_at = datetime.now(timezone.utc)
                        metric.upload_attempts += 1
                        metric.last_upload_error = None
                        successful_count += 1

                        logger.info(f'Uploaded metric {metric.id} to Replicated')

                    except Exception as e:
                        metric.upload_attempts += 1
                        metric.last_upload_error = str(e)
                        logger.error(f'Error uploading metric {metric.id}: {e}')

                session.commit()
                logger.info(
                    f'Successfully uploaded {successful_count}/{len(pending_metrics)} metrics'
                )

        except Exception as e:
            logger.error(f'Error during metrics upload: {e}', exc_info=True)

    def _get_admin_email(self, session) -> Optional[str]:
        """Determine admin email from environment or database."""
        # Try environment variable first
        admin_email = os.getenv('OPENHANDS_ADMIN_EMAIL')
        if admin_email:
            logger.info(
                'Using admin email from OPENHANDS_ADMIN_EMAIL environment variable'
            )
            return admin_email

        # Try first user who accepted ToS
        try:
            first_user = (
                session.query(UserSettings)
                .filter(UserSettings.accepted_tos.isnot(None))
                .filter(UserSettings.email.isnot(None))
                .order_by(UserSettings.accepted_tos)
                .first()
            )
            if first_user and first_user.email:
                logger.info(f'Using first active user email: {first_user.email}')
                return first_user.email
        except Exception as e:
            logger.error(f'Error determining admin email: {e}')

        return None

    def _get_or_create_identity(self, session, admin_email: str) -> TelemetryIdentity:
        """Get or create telemetry identity with customer and instance IDs."""
        identity = (
            session.query(TelemetryIdentity).filter(TelemetryIdentity.id == 1).first()
        )

        if not identity:
            identity = TelemetryIdentity(id=1)
            session.add(identity)

        # Set customer_id to admin email if not already set
        if not identity.customer_id:
            identity.customer_id = admin_email

        # Generate instance_id using Replicated SDK if not set
        if not identity.instance_id:
            if REPLICATED_AVAILABLE:
                try:
                    client = ReplicatedClient(
                        publishable_key=self.replicated_publishable_key,
                        app_slug=self.replicated_app_slug,
                    )
                    # Create customer and instance to get IDs
                    customer = client.customer.get_or_create(email_address=admin_email)
                    instance = customer.get_or_create_instance()
                    identity.instance_id = instance.instance_id
                except Exception as e:
                    logger.error(f'Error generating instance_id: {e}')
                    # Generate a fallback UUID if Replicated SDK fails
                    import uuid

                    identity.instance_id = str(uuid.uuid4())
            else:
                # Generate a fallback UUID if Replicated SDK not available
                import uuid

                identity.instance_id = str(uuid.uuid4())

        session.commit()
        return identity

    def get_license_warning_status(self) -> dict:
        """Get current license warning status for UI display.

        Returns:
            dict with 'should_warn', 'days_since_upload', and 'message' keys
        """
        try:
            with session_maker() as session:
                last_uploaded = (
                    session.query(TelemetryMetrics)
                    .filter(TelemetryMetrics.uploaded_at.isnot(None))
                    .order_by(TelemetryMetrics.uploaded_at.desc())
                    .first()
                )

                if not last_uploaded:
                    return {
                        'should_warn': False,
                        'days_since_upload': None,
                        'message': 'No uploads yet',
                    }

                days_since_upload = (
                    datetime.now(timezone.utc) - last_uploaded.uploaded_at
                ).days

                should_warn = days_since_upload > self.license_warning_threshold_days

                return {
                    'should_warn': should_warn,
                    'days_since_upload': days_since_upload,
                    'message': f'Last upload: {days_since_upload} days ago',
                }
        except Exception as e:
            logger.error(f'Error getting license warning status: {e}')
            return {
                'should_warn': False,
                'days_since_upload': None,
                'message': f'Error: {str(e)}',
            }


# Global singleton instance
telemetry_service = TelemetryService()
