import os
import tempfile

import pytest

from db.migrations import run_migrations


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    run_migrations(path)
    yield path
    os.unlink(path)
