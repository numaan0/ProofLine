import sqlite3

from sqlalchemy import create_engine

import app.models.inspection_models  # noqa: F401
from app.services.persistence import Base, _add_missing_columns


def test_missing_columns_are_added_to_old_tables(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    # Shape of an observations table created by an earlier model version.
    con.execute("CREATE TABLE observations (id VARCHAR PRIMARY KEY, inspection_id VARCHAR NOT NULL, "
                "observation_text TEXT NOT NULL, metadata JSON)")
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        _add_missing_columns(conn)

    cols = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(observations)")}
    assert {"meta_data", "image_id", "relevant_task_ids", "limitations", "created_at"} <= cols
