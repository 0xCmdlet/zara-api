"""Main entry point for Zara availability checker"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from .checker import AvailabilityChecker
from .config import load_env_config, load_products
from .state_manager import StateManager


def setup_logging(log_level: str = "INFO") -> None:
    """Configure logging with console and file handlers"""
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Configure logging
    log_format = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler (INFO and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    # File handler (DEBUG and above) with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "zara_checker.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Zara Product Availability Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--interval",
        type=int,
        help="Check interval in seconds (default: from .env or 300)",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for testing)",
    )

    parser.add_argument(
        "--config",
        type=str,
        default="products.json",
        help="Path to products configuration file (default: products.json)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: from .env or INFO)",
    )

    return parser.parse_args()


async def async_main() -> None:
    """Async main function"""
    args = parse_args()

    # Load configuration
    try:
        env_config = load_env_config()
    except Exception as e:
        logging.error(f"Failed to load environment configuration: {e}")
        sys.exit(1)

    # Setup logging
    log_level = args.log_level or env_config.log_level
    setup_logging(log_level)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Zara Product Availability Checker Starting")
    logger.info("=" * 60)

    # Load products
    try:
        products = load_products(args.config)
        logger.info(f"Loaded {len(products)} products from {args.config}")
    except Exception as e:
        logger.error(f"Failed to load products: {e}")
        sys.exit(1)

    # Initialize state manager
    state_manager = StateManager()
    logger.info("State manager initialized")

    # Create checker
    checker = AvailabilityChecker(
        products=products,
        env_config=env_config,
        state_manager=state_manager,
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, saving state and exiting...")
        state_manager.save_state()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run checker
    try:
        if args.once:
            logger.info("Running in single-check mode")
            await checker.run_once()
            logger.info("Check completed. Exiting.")
        else:
            interval = args.interval or env_config.check_interval
            logger.info(f"Running in continuous mode (interval: {interval}s)")
            await checker.run_continuous(interval)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        state_manager.save_state()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        state_manager.save_state()
        sys.exit(1)
    finally:
        logger.info("Zara Product Availability Checker Stopped")


def main() -> None:
    """Main entry point"""
    # Import logging.handlers here to avoid issues
    import logging.handlers

    asyncio.run(async_main())


if __name__ == "__main__":
    main()
