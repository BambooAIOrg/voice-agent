from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from sqlalchemy import event
from logger import get_logger

logger = get_logger(__name__)

SQLALCHEMY_DATABASE_URI = os.getenv("MYSQL_DATABASE_URI") or ''
ASYNC_SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('mysql+pymysql://', 'mysql+aiomysql://')
SQLALCHEMY_TRACK_MODIFICATIONS = False

engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    # echo=True,
    pool_size=20,
    max_overflow=10,
    pool_timeout=3,
    pool_recycle=1800,  # 30 minutes
    connect_args={
        "init_command": "SET SESSION wait_timeout=28800, SESSION interactive_timeout=28800",
    },
)

async_engine = create_async_engine(
    ASYNC_SQLALCHEMY_DATABASE_URI,
    pool_size=20,
    max_overflow=10,
    pool_timeout=3,
    pool_recycle=1800,  # 30 minutes
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
async_session_maker = async_sessionmaker(
    async_engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

@event.listens_for(engine, 'connect')
def receive_connect(dbapi_connection, connection_record):
    logger.info("Database connection established successfully")

Base = declarative_base()