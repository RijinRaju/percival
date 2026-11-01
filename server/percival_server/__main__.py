from __future__ import annotations

import os
import sys

import uvicorn

from percival.naming import ENV_PREFIX
from percival_server import logs
from percival_server.config import ConfigError, ServerConfig
from percival_server.main import create_app


def main() -> None:
    logs.setup(os.environ.get(ENV_PREFIX + "LOG_LEVEL", "INFO"))
    try:
        app = create_app(ServerConfig.from_env())
    except ConfigError as exc:
        print(f"percival-server: {exc}", file=sys.stderr)
        sys.exit(2)

    uvicorn.run(
        app,
        host=os.environ.get(ENV_PREFIX + "HOST", "127.0.0.1"),
        port=int(os.environ.get(ENV_PREFIX + "PORT", "8080")),
        log_config=None,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
