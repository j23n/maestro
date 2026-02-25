from sqlmodel import create_engine, Session
from typing import Annotated
from fastapi import Depends
from maestro.settings import Settings

engine = create_engine(Settings().database_url)


def get_session():
    with Session(engine) as session:
        yield session


TABLE_CHUNKS = "italian_chunks"

SessionDep = Annotated[Session, Depends(get_session)]
