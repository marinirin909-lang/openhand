import json
import pathlib
import uuid
from datetime import datetime
from uuid import UUID

import pytest
from server.auth.token_manager import KeycloakUserInfo
from server.constants import ORG_SETTINGS_VERSION
from server.verified_models.verified_model_service import (
    StoredVerifiedModel,  # noqa: F401
)
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from storage.api_key import ApiKey  # noqa: F401
from storage.base import Base
from storage.billing_session import BillingSession
from storage.conversation_work import ConversationWork
from storage.device_code import DeviceCode  # noqa: F401
from storage.feedback import Feedback
from storage.github_app_installation import GithubAppInstallation
from storage.org import Org
from storage.org_invitation import OrgInvitation  # noqa: F401
from storage.org_member import OrgMember
from storage.role import Role
from storage.slack_conversation import SlackConversation  # noqa: F401
from storage.stored_conversation_metadata import StoredConversationMetadata
from storage.stored_conversation_metadata_saas import (
    StoredConversationMetadataSaas,
)
from storage.stored_offline_token import StoredOfflineToken
from storage.stripe_customer import StripeCustomer
from storage.user import User
from testcontainers.postgres import PostgresContainer
from xdist import is_xdist_controller

# ---------------------------------------------------------------------------
# PostgreSQL container lifecycle — managed by the xdist controller
# ---------------------------------------------------------------------------

_PG_INFO_FILE = '.pytest_pg_info.json'


def _pg_info_path(session):
    """Return the path to the shared PG connection info file."""
    return pathlib.Path(session.config.rootpath) / _PG_INFO_FILE


def _extract_pg_info(pg):
    """Extract connection info dict from a running PostgresContainer."""
    return {
        'host': pg.get_container_host_ip(),
        'port': pg.get_exposed_port(5432),
        'user': pg.username,
        'password': pg.password,
        'default_dbname': pg.dbname,
    }


def _import_all_models():
    """Import every Base subclass so Base.metadata knows about all tables.

    These imports are deliberately kept out of module scope because some
    transitively load C-extension modules that spawn threads, which makes
    the process unsafe to fork() (used by pytest --forked).  Importing
    them here — inside the controller only — avoids that problem.
    """
    import importlib
    import logging
    import pkgutil

    import storage as _storage_pkg

    log = logging.getLogger(__name__)
    for _importer, modname, _ispkg in pkgutil.walk_packages(
        _storage_pkg.__path__, prefix='storage.'
    ):
        try:
            importlib.import_module(modname)
        except ImportError as e:
            log.warning('Failed to import %s: %s', modname, e)


def _create_template_db(info):
    """Create a template database with all tables via Base.metadata.create_all()."""
    _import_all_models()

    default_url = (
        f"postgresql+psycopg2://{info['user']}:{info['password']}"
        f"@{info['host']}:{info['port']}/{info['default_dbname']}"
    )
    default_engine = create_engine(default_url, isolation_level='AUTOCOMMIT')
    with default_engine.connect() as conn:
        conn.execute(text('CREATE DATABASE template_test'))
    default_engine.dispose()

    template_url = (
        f"postgresql+psycopg2://{info['user']}:{info['password']}"
        f"@{info['host']}:{info['port']}/template_test"
    )
    template_engine = create_engine(template_url)
    Base.metadata.create_all(template_engine)
    template_engine.dispose()


def pytest_sessionstart(session):
    """Start the PostgreSQL container on the controller and create the template DB.

    The controller (or non-xdist process) starts the container, creates the
    template database, and writes connection info to a file.  Workers read the
    file to discover the shared container.
    """
    if is_xdist_controller(session) or not hasattr(session.config, 'workerinput'):
        # Controller or non-xdist: start container and create template DB
        pg = PostgresContainer('postgres:16-alpine')
        pg.start()
        session.config._pg_container = pg
        info = _extract_pg_info(pg)
        _create_template_db(info)
        _pg_info_path(session).write_text(json.dumps(info))
        session.config._pg_info = info
    else:
        # xdist worker: read connection info written by the controller
        session.config._pg_info = json.loads(_pg_info_path(session).read_text())


def pytest_sessionfinish(session, exitstatus):
    """Stop the PostgreSQL container and clean up the info file."""
    pg = getattr(session.config, '_pg_container', None)
    if pg is not None:
        pg.stop()
        info_path = _pg_info_path(session)
        if info_path.exists():
            info_path.unlink()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def create_keycloak_user_info():
    """Fixture that returns a factory function to create KeycloakUserInfo models.

    Usage:
        def test_example(create_keycloak_user_info):
            user_info = create_keycloak_user_info(sub='user123', email='test@example.com')
    """

    def _create(**kwargs) -> KeycloakUserInfo:
        defaults = {
            'sub': 'test_user_id',
            'preferred_username': 'test_user',
        }
        defaults.update(kwargs)
        return KeycloakUserInfo(**defaults)

    return _create


@pytest.fixture(scope='session')
def _pg_template_db(request):
    """Return the shared PostgreSQL connection info from config."""
    return request.config._pg_info


# ---------------------------------------------------------------------------
# Function-scoped: one cloned database per test
# ---------------------------------------------------------------------------


@pytest.fixture(scope='function')
def _test_db(_pg_template_db):
    """Clone the template database for a single test."""
    info = _pg_template_db
    db_name = f'test_{uuid.uuid4().hex[:12]}'
    default_url = (
        f"postgresql+psycopg2://{info['user']}:{info['password']}"
        f"@{info['host']}:{info['port']}/{info['default_dbname']}"
    )

    default_engine = create_engine(default_url, isolation_level='AUTOCOMMIT')
    with default_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}" TEMPLATE template_test'))
    default_engine.dispose()

    yield {**info, 'dbname': db_name}

    # Teardown: terminate connections then drop the test database
    default_engine = create_engine(default_url, isolation_level='AUTOCOMMIT')
    with default_engine.connect() as conn:
        conn.execute(
            text(
                f'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    default_engine.dispose()


@pytest.fixture
def engine(_test_db):
    """Create a sync engine pointing at the per-test PostgreSQL database."""
    info = _test_db
    url = (
        f"postgresql+psycopg2://{info['user']}:{info['password']}"
        f"@{info['host']}:{info['port']}/{info['dbname']}"
    )
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
async def async_engine(_test_db):
    """Create an async engine pointing at the per-test PostgreSQL database."""
    info = _test_db
    url = (
        f"postgresql+asyncpg://{info['user']}:{info['password']}"
        f"@{info['host']}:{info['port']}/{info['dbname']}"
    )
    eng = create_async_engine(url)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_maker(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
async def async_session_maker(async_engine):
    """Create an async session maker bound to the async engine."""
    return async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def add_minimal_fixtures(session_maker):
    with session_maker() as session:
        # Insert FK parent rows first: Org, Role, User
        session.add(
            Org(
                id=uuid.UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                name='mock-org',
                org_version=ORG_SETTINGS_VERSION,
                enable_default_condenser=True,
                enable_proactive_conversation_starters=True,
            )
        )
        session.add(
            Role(
                id=1,
                name='admin',
                rank=1,
            )
        )
        session.flush()
        session.add(
            User(
                id=uuid.UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                current_org_id=uuid.UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                user_consents_to_analytics=True,
            )
        )
        session.flush()

        # Now insert rows that depend on Org/Role/User
        session.add(
            OrgMember(
                org_id=uuid.UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                user_id=uuid.UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                role_id=1,
                llm_api_key='mock-api-key',
                status='active',
            )
        )
        session.add(
            StoredConversationMetadata(
                conversation_id='mock-conversation-id',
                created_at=datetime.fromisoformat('2025-03-07'),
                last_updated_at=datetime.fromisoformat('2025-03-08'),
                accumulated_cost=5.25,
                prompt_tokens=500,
                completion_tokens=250,
                total_tokens=750,
            )
        )
        session.flush()
        session.add(
            StoredConversationMetadataSaas(
                conversation_id='mock-conversation-id',
                user_id=UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
                org_id=UUID('5594c7b6-f959-4b81-92e9-b09c206f5081'),
            )
        )
        session.add(
            BillingSession(
                id='mock-billing-session-id',
                user_id='mock-user-id',
                status='completed',
                price=20,
                price_code='NA',
                created_at=datetime.fromisoformat('2025-03-03'),
                updated_at=datetime.fromisoformat('2025-03-04'),
            )
        )
        session.add(
            Feedback(
                id='mock-feedback-id',
                version='1.0',
                email='user@all-hands.dev',
                polarity='positive',
                permissions='public',
                trajectory=[],
            )
        )
        session.add(
            GithubAppInstallation(
                installation_id='mock-installation-id',
                encrypted_token='',
                created_at=datetime.fromisoformat('2025-03-05'),
                updated_at=datetime.fromisoformat('2025-03-06'),
            )
        )
        session.add(
            StoredOfflineToken(
                user_id='mock-user-id',
                offline_token='mock-offline-token',
                created_at=datetime.fromisoformat('2025-03-07'),
                updated_at=datetime.fromisoformat('2025-03-08'),
            )
        )
        session.add(
            StripeCustomer(
                keycloak_user_id='mock-user-id',
                stripe_customer_id='mock-stripe-customer-id',
                created_at=datetime.fromisoformat('2025-03-09'),
                updated_at=datetime.fromisoformat('2025-03-10'),
            )
        )
        session.add(
            ConversationWork(
                conversation_id='mock-conversation-id',
                user_id='mock-user-id',
                created_at=datetime.fromisoformat('2025-03-07'),
                updated_at=datetime.fromisoformat('2025-03-08'),
            )
        )
        session.commit()


@pytest.fixture
def session_maker_with_minimal_fixtures(engine):
    session_maker = sessionmaker(bind=engine)
    add_minimal_fixtures(session_maker)
    return session_maker
