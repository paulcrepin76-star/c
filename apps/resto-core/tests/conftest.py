import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/resto-pytest.db")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("RESTO_API_KEY", "test")
