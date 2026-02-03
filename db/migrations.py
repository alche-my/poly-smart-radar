from db.models import init_db


def run_migrations(db_path: str) -> None:
    init_db(db_path)
