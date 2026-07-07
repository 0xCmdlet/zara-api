"""Entry point for the H&M availability checker.

H&M is Akamai-protected, so this uses the same real-Chrome browser session as
Zara. Run continuously (check every 60s):
    python -m src.hm_main

Test one cycle without sending emails:
    python -m src.hm_main --once --dry-run
"""

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .browser_session import BrowserSession
from .config import load_env_config
from .hm_checker import HmChecker
from .hm_models import HmProductsConfig
from .main import setup_logging
from .mango_state import MangoStateManager

_DEFAULT_BOOTSTRAP = "https://www2.hm.com/de_de/index.html"


def load_hm_products(config_path: str) -> list:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    config = HmProductsConfig(**data)
    if not config.products:
        raise ValueError("No products defined in configuration file")
    return config.products


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H&M Availability Checker")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds between products")
    parser.add_argument("--config", type=str, default="hm_products.json")
    parser.add_argument("--dry-run", action="store_true", help="Detect only; don't email")
    parser.add_argument(
        "--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()

    try:
        env_config = load_env_config()
    except Exception as e:
        logging.error(f"Failed to load environment configuration: {e}")
        sys.exit(1)

    setup_logging(args.log_level or env_config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("H&M Product Availability Checker Starting")
    logger.info("=" * 60)

    try:
        products = load_hm_products(args.config)
        logger.info(f"Loaded {len(products)} product(s) from {args.config}")
    except Exception as e:
        logger.error(f"Failed to load products: {e}")
        sys.exit(1)

    # Bootstrap on an hm.com page so the in-browser fetch carries Akamai cookies
    # and the correct same-site Origin.
    bootstrap = (
        os.getenv("HM_BOOTSTRAP_URL")
        or products[0].link
        or _DEFAULT_BOOTSTRAP
    )
    session = BrowserSession(
        bootstrap_url=bootstrap,
        user_agent=env_config.zara_user_agent,
        headless=env_config.browser_headless,
        timeout=env_config.browser_timeout,
        channel=env_config.browser_channel,
        proxy=env_config.browser_proxy,
    )

    try:
        await session.start()
    except Exception as e:
        logger.error(f"Could not establish H&M browser session: {e}")
        await session.close()
        sys.exit(1)

    state = MangoStateManager("hm_state.json")
    checker = HmChecker(
        products=products,
        env_config=env_config,
        session=session,
        state=state,
        delay_between=args.delay,
        dry_run=args.dry_run,
    )

    try:
        if args.once:
            logger.info("Running in single-check mode")
            await checker.check_once()
            logger.info("Check completed. Exiting.")
        else:
            logger.info(f"Running in continuous mode (interval: {args.interval}s)")
            await checker.run_continuous(args.interval)
    except KeyboardInterrupt:
        logger.info("Interrupted by user; state saved.")
        state.save()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        state.save()
        sys.exit(1)
    finally:
        await session.close()
        logger.info("H&M Product Availability Checker Stopped")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
