"""
Database models for Escrow Bridge.
"""
from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
import secrets
import hashlib
import bcrypt

Base = declarative_base()


class SettledEvent(Base):
    """Model for tracking PaymentSettled events."""

    __tablename__ = 'settled_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    escrow_id = Column(String(66), unique=True, nullable=False, index=True)
    network = Column(String(50), nullable=False)
    payer = Column(String(42), nullable=False)
    settled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    amount_settled_tokens = Column(Float, nullable=False)
    amount_settled_usd = Column(Float, nullable=False)

    def __repr__(self):
        return f"<SettledEvent(escrow_id='{self.escrow_id[:16]}...', usd=${self.amount_settled_usd:.2f})>"


class APIKey(Base):
    """Model for storing API keys for authentication."""

    __tablename__ = 'api_keys'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)  # User-friendly name
    key_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA256 hash of key
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<APIKey(name='{self.name}', created_at={self.created_at}, active={self.is_active})>"

    @staticmethod
    def generate_key():
        """Generate a new API key (48 bytes = 96 hex chars)."""
        return secrets.token_hex(48)

    @staticmethod
    def hash_key(key):
        """Hash an API key using SHA256 then bcrypt (bcrypt has 72-byte limit)."""
        # First hash with SHA256 to reduce size
        sha256_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # Then bcrypt the SHA256 hash
        return bcrypt.hashpw(sha256_hash.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_hash(key, hash_value):
        """Verify an API key against its bcrypt hash."""
        # First hash with SHA256 to match storage format
        sha256_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # Then verify against bcrypt hash
        return bcrypt.checkpw(sha256_hash.encode("utf-8"), hash_value.encode("utf-8"))

    @classmethod
    def create(cls, name, session):
        """Create a new API key and save to database."""
        key = cls.generate_key()
        key_hash = cls.hash_key(key)

        api_key = cls(name=name, key_hash=key_hash)
        session.add(api_key)
        session.commit()

        return key, api_key  # Return both the plaintext key (to show to user) and the DB object

    @classmethod
    def verify_key(cls, key, session):
        """Verify an API key and return the key object if valid."""
        # Query all active keys and verify the provided key
        api_keys = session.query(cls).filter_by(is_active=True).all()

        for api_key in api_keys:
            if cls.verify_hash(key, api_key.key_hash):
                # Update last_used_at
                api_key.last_used_at = datetime.utcnow()
                session.commit()
                return api_key

        return None


# Database configuration
_engine = None
_SessionMaker = None


def get_database_url():
    """Get database URL from environment variables."""
    return os.getenv('DATABASE_URL')


def init_db(database_url=None):
    """Initialize database and create tables."""
    global _engine, _SessionMaker
    url = database_url or get_database_url()
    if not url:
        raise ValueError("DATABASE_URL environment variable is not set")
    _engine = create_engine(url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(_engine)
    _SessionMaker = sessionmaker(bind=_engine)
    return _engine


def get_session():
    """Get a database session."""
    global _SessionMaker
    if _SessionMaker is None:
        init_db()
    return _SessionMaker()


def get_session_maker(database_url=None):
    """Get SQLAlchemy session maker."""
    url = database_url or get_database_url()
    if not url:
        raise ValueError("DATABASE_URL environment variable is not set")
    engine = create_engine(url, echo=False, pool_pre_ping=True)
    return sessionmaker(bind=engine)
