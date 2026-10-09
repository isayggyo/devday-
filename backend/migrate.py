import argparse
import os

from alembic import command
from alembic.config import Config

from .config import get_settings, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        settings = get_settings()
        url = settings.test_database_url.get_secret_value()
        if not url or url == settings.database_url.get_secret_value():
            raise SystemExit("A separate TEST_DATABASE_URL is required")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


if __name__ == "__main__":
    main()
