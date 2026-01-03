"""Availability checker orchestration"""

import asyncio
import logging
from typing import Optional

from .api_client import ZaraApiClient, ApiError
from .config import EnvConfig
from .csv_logger import CsvLogger
from .models import Product, ApiResponse, SkuAvailability
from .notifier import EmailNotifier
from .state_manager import StateManager


logger = logging.getLogger(__name__)


class AvailabilityChecker:
    """Orchestrates product availability checking"""

    def __init__(
        self,
        products: list[Product],
        env_config: EnvConfig,
        state_manager: StateManager,
    ):
        self.products = products
        self.env_config = env_config
        self.state_manager = state_manager

        # Initialize notifier
        self.notifier = EmailNotifier(
            smtp_host=env_config.smtp_host,
            smtp_port=env_config.smtp_port,
            smtp_username=env_config.smtp_username,
            smtp_password=env_config.smtp_password,
            email_from=env_config.email_from,
            email_to=env_config.email_to,
        )

        # Initialize CSV logger
        self.csv_logger = CsvLogger()

    async def _check_single_product(
        self,
        api_client: ZaraApiClient,
        product: Product,
    ) -> tuple[Product, Optional[ApiResponse], Optional[Exception]]:
        """
        Check a single product availability

        Returns:
            Tuple of (product, api_response, error)
        """
        try:
            api_response = await api_client.check_availability(product)
            return (product, api_response, None)
        except Exception as e:
            logger.error(f"Error checking {product.name} (SKU: {product.sku}): {e}")
            return (product, None, e)

    async def check_all_products(self) -> list[tuple[Product, Optional[ApiResponse], Optional[Exception]]]:
        """
        Check all products concurrently

        Returns:
            List of (product, api_response, error) tuples
        """
        logger.info(f"Starting availability check for {len(self.products)} products")

        async with ZaraApiClient(
            user_agent=self.env_config.zara_user_agent,
        ) as api_client:
            # Create tasks for all products
            tasks = [
                self._check_single_product(api_client, product)
                for product in self.products
            ]

            # Run all checks concurrently
            results = await asyncio.gather(*tasks)

        logger.info(f"Completed availability check for {len(self.products)} products")
        return results

    def _find_sku_in_response(
        self,
        api_response: ApiResponse,
        target_sku: int,
    ) -> Optional[SkuAvailability]:
        """Find specific SKU in API response"""
        for sku_avail in api_response.skusAvailability:
            if sku_avail.sku == target_sku:
                return sku_avail
        return None

    def process_results(
        self,
        results: list[tuple[Product, Optional[ApiResponse], Optional[Exception]]],
    ) -> None:
        """
        Process check results and send notifications

        Args:
            results: List of (product, api_response, error) tuples
        """
        for product, api_response, error in results:
            # Skip if there was an error
            if error is not None or api_response is None:
                # Update state as unknown if we couldn't check
                self.state_manager.update_state(
                    sku=product.sku,
                    availability="unknown",
                    notified=False,
                )
                continue

            # Find the specific SKU we're tracking
            sku_availability = self._find_sku_in_response(api_response, product.sku)

            if sku_availability is None:
                logger.warning(
                    f"SKU {product.sku} not found in API response for {product.name}"
                )
                self.state_manager.update_state(
                    sku=product.sku,
                    availability="unknown",
                    notified=False,
                )
                continue

            # Check if we should notify
            should_notify = self.state_manager.should_notify(
                sku=product.sku,
                current_status=sku_availability.availability,
            )

            logger.info(
                f"{product.name} (SKU: {product.sku}): "
                f"{sku_availability.availability} "
                f"(notify: {should_notify})"
            )

            # Send notification if needed
            notified = False
            if should_notify:
                notified = self.notifier.send_notification(product, sku_availability)
                if notified:
                    logger.info(
                        f"Notification sent for {product.name} (SKU: {product.sku})"
                    )
                    # Log to CSV
                    self.csv_logger.log_availability(product, sku_availability)
                    logger.debug(f"Logged availability to CSV for {product.name}")
                else:
                    logger.error(
                        f"Failed to send notification for {product.name} (SKU: {product.sku})"
                    )

            # Update state
            self.state_manager.update_state(
                sku=product.sku,
                availability=sku_availability.availability,
                notified=notified,
            )

        # Save state after processing all results
        self.state_manager.save_state()

    async def run_once(self) -> None:
        """Run availability check once"""
        results = await self.check_all_products()
        self.process_results(results)

    async def run_continuous(self, interval_seconds: int) -> None:
        """
        Run availability check continuously

        Args:
            interval_seconds: Time to wait between checks
        """
        logger.info(f"Starting continuous checking (interval: {interval_seconds}s)")

        try:
            while True:
                await self.run_once()
                logger.info(f"Waiting {interval_seconds}s until next check...")
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Continuous checking cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in continuous checking: {e}")
            raise
