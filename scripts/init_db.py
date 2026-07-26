from __future__ import annotations

from database.session import create_database


def main() -> None:
    create_database()


if __name__ == "__main__":
    main()
