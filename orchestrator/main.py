import argparse
import asyncio
import logging
import signal
import sys

from config import Settings
from .pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WiZ Music Sync")
    parser.add_argument("--mode", choices=["reactive", "ambient"], default="reactive")
    parser.add_argument(
        "--vibe",
        choices=["auto", "fiesta", "chill", "rock", "hyperpop", "classical"],
        default="auto",
        help="Modo de dinámica: auto (adapta solo) o forzado",
    )
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = Settings()
    settings.mode = args.mode
    settings.director.mode = args.vibe
    settings.debug = args.debug

    pipeline = Pipeline(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, pipeline.request_stop)

    logger.info("Starting WiZ Music Sync")
    logger.info(f"Bulb: {settings.wiz.ip}")
    logger.info(f"Mode: {settings.mode}")
    if settings.debug:
        logger.info("Debug visualization enabled")

    try:
        await pipeline.run()
    except KeyboardInterrupt:
        pass
    finally:
        await pipeline.stop()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
