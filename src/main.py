#!/usr/bin/env python3
"""Entry point: starts the scheduler and the web server together."""
import asyncio
import logging

import uvicorn

from src.config import HOST, PORT
from src.scheduler import run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


async def start_server():
    """Start uvicorn server."""
    config = uvicorn.Config(
        "src.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Run scheduler and server concurrently."""
    await asyncio.gather(
        run_scheduler(),
        start_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())
