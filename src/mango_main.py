"""Entry point for the Mango availability checker.

Run continuously (check every 60s, 5s between items):
    python -m src.mango_main

Run once (testing):
    python -m src.mango_main --once
"""

import argparse
import json
import logging
import logging.handlers
import sys
from pathlib import Path

from .config import load_env_config
from .main import setup_logging
from .mango_checker import MangoChecker
from .mango_client import MangoClient
from .mango_models import MangoProductsConfig
from .mango_state import MangoStateManager


def load_mango_products(config_path: str) -> list:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    config = MangoProductsConfig(**data)
    if not config.products:
        raise ValueError("No products defined in configuration file")
    return config.products


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mango Availability Checker")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument(
        "--interval", type=int, default=60, help="Seconds between full cycles (default 60)"
    )
    parser.add_argument(
        "--delay", type=float, default=5.0,
        help="Seconds between per-product requests (default 5)",
    )
    parser.add_argument(
        "--config", type=str, default="mango_products.json",
        help="Path to Mango products config (default mango_products.json)",
    )
    parser.add_argument(
        "--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        env_config = load_env_config()
    except Exception as e:
        logging.error(f"Failed to load environment configuration: {e}")
        sys.exit(1)

    setup_logging(args.log_level or env_config.log_level)
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Mango Product Availability Checker Starting")
    logger.info("=" * 60)

    try:
        products = load_mango_products(args.config)
        logger.info(f"Loaded {len(products)} product(s) from {args.config}")
    except Exception as e:
        logger.error(f"Failed to load products: {e}")
        sys.exit(1)

    client = MangoClient(
        user_agent=env_config.zara_user_agent,
        timeout=env_config.browser_timeout,
    )
    state = MangoStateManager()
    checker = MangoChecker(
        products=products,
        env_config=env_config,
        client=client,
        state=state,
        delay_between=args.delay,
    )

    try:
        if args.once:
            logger.info("Running in single-check mode")
            checker.check_once()
            logger.info("Check completed. Exiting.")
        else:
            checker.run_continuous(args.interval)
    except KeyboardInterrupt:
        logger.info("Interrupted by user; state saved.")
        state.save()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        state.save()
        sys.exit(1)


if __name__ == "__main__":
    main()
