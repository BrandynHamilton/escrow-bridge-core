"""
Database models for Escrow Bridge.
"""
from sqlalchemy import Column, String, Float, DateTime, Integer, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

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
