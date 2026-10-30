import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    if os.getenv("VERCEL"):
        raise RuntimeError("DATABASE_URL must point to a persistent database in Vercel")
    DATABASE_URL = "sqlite:///./inetz-dev.db"
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
DB = sessionmaker(engine, expire_on_commit=False)
