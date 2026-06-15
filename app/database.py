"""SQLAlchemy engine/session setup."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

# For Postgres (Supabase), connections can be dropped after a period of inactivity.
# pool_pre_ping checks a connection is still alive before using it (and transparently
# reconnects if not), and pool_recycle proactively retires connections before the
# server's idle timeout. This prevents the intermittent
# "server closed the connection unexpectedly" 500s.
_is_sqlite = settings.database_url.startswith("sqlite")
_pool_kwargs = {} if _is_sqlite else {
    "pool_pre_ping": True,
    "pool_recycle": 300,      # recycle connections every 5 min
    "pool_size": 10,
    "max_overflow": 20,
}
engine = create_engine(
    settings.database_url, connect_args=connect_args, echo=False, **_pool_kwargs
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()