from __future__ import annotations

import uvicorn

from config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=False)


if __name__ == "__main__":
    main()
