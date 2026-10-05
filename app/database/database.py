from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings, ROOT

(ROOT / "data").mkdir(exist_ok=True)
_sqlite = settings.DATABASE_URL.startswith("sqlite")
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if _sqlite else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
