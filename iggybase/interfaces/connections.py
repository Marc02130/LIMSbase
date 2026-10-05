from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from config import Config
import logging

SpinalBase = declarative_base()
_scoped = None


def spinal_db_session():
    """Open the SPINAL database on first use.

    Importing this module does not connect. SPINAL_DATABASE_URI is optional.
    """
    global _scoped
    if _scoped is None:
        uri = Config.SPINAL_DATABASE_URI
        name = Config.SPINAL_DB_NAME
        if not uri or not name:
            raise RuntimeError(
                "SPINAL_DATABASE_URI and SPINAL_DB_NAME are not set"
            )
        if not uri.endswith("/"):
            uri += "/"
        engine = create_engine(uri + name, pool_recycle=3600)
        _scoped = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=engine)
        )
        SpinalBase.query = _scoped.query_property()
        try:
            SpinalBase.metadata.create_all(bind=engine)
        except Exception:
            logging.error("Could not connect to spinal DB")
            raise
    return _scoped()
