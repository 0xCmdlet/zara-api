"""Availability checker orchestration"""

import asyncio
import logging
from typing import Optional

from .banned_skus import BannedSkuStore
from .browser_session import BrowserSession, AuthenticationError
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
        session: BrowserSession,
        banned_store: BannedSkuStore,
        max_refresh_attempts: int = 2,
    ):
        self.products = products
        self.env_config = env_config
        self.state_manager = state_manager
        self.session = session
        self.banned_store = banned_store
        self.max_refresh_attempts = max_refresh_attempts

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
        product: Product,
    ) -> tuple[Product, Optional[ApiResponse], Optional[Exception]]:
        """
        Check a single product availability

        Returns:
            Tuple of (product, api_response, error)
        """
        try:
            api_response = await self.session.check_availability(product)
            return (product, api_response, None)
        except Exception as e:
            logger.error(f"Error checking {product.name} (SKU: {product.sku}): {e}")
            return (product, None, e)

    async def check_all_products(self) -> list[tuple[Product, Optional[ApiResponse], Optional[Exception]]]:
        """
        Check all products concurrently via the shared browser session

        Returns:
            List of (product, api_response, error) tuples
        """
        logger.info(f"Starting availability check for {len(self.products)} products")

        tasks = [self._check_single_product(product) for product in self.products]
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

    @staticmethod
    def _returned_skus(api_response: ApiResponse) -> set[int]:
        """All SKUs present in an API response."""
        return {s.sku for s in api_response.skusAvailability}

    def _detect_stale(
        self,
        results: list[tuple[Product, Optional[ApiResponse], Optional[Exception]]],
    ) -> tuple[bool, set[int]]:
        """Detect whether this batch came from a stale/blocked session.

        A stale session is identified by any of:
        - Every product failed with an authentication error.
        - Multiple products returned the *same* SKU set, none of which match the
          SKU we actually track (Zara served one default "fake" product).
        - A product's tracked SKU is absent and every SKU it returned is already
          on the banned list.

        Returns:
            (is_stale, fake_skus) where ``fake_skus`` are the SKUs to ban.
        """
        responses = [(p, r) for p, r, e in results if r is not None]
        auth_errors = [e for _, _, e in results if isinstance(e, AuthenticationError)]

        # Everything failed authentication -> definitely stale.
        if not responses and auth_errors:
            return True, set()

        stale = False
        fake_skus: set[int] = set()

        # Signature 1: all products returned an identical SKU set, none tracked.
        sku_sets = [frozenset(self._returned_skus(r)) for _, r in responses]
        if len(sku_sets) > 1 and len(set(sku_sets)) == 1:
            any_tracked = any(
                self._find_sku_in_response(r, p.sku) is not None
                for p, r in responses
            )
            if not any_tracked:
                stale = True
                fake_skus |= set(sku_sets[0])

        # Signature 2: tracked SKU missing and every returned SKU is banned.
        for p, r in responses:
            if self._find_sku_in_response(r, p.sku) is not None:
                continue
            returned = self._returned_skus(r)
            if returned and returned <= self.banned_store.skus:
                stale = True
                fake_skus |= returned

        return stale, fake_skus

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
        """Run availability check once, refreshing the session if stale.

        If the batch looks like a stale/blocked session, the offending SKUs are
        added to the banned list, the browser session is renewed, and the check
        is retried (up to ``max_refresh_attempts`` times).
        """
        for attempt in range(self.max_refresh_attempts + 1):
            results = await self.check_all_products()
            stale, fake_skus = self._detect_stale(results)

            if not stale:
                self.process_results(results)
                return

            if fake_skus:
                newly_banned = self.banned_store.add(fake_skus)
                if newly_banned:
                    self.banned_store.save()
                    logger.warning(
                        f"Detected fake SKUs from stale session, banned: "
                        f"{sorted(newly_banned)}"
                    )

            if attempt < self.max_refresh_attempts:
                logger.warning(
                    f"Stale session detected "
                    f"(attempt {attempt + 1}/{self.max_refresh_attempts}). "
                    f"Renewing browser session..."
                )
                try:
                    await self.session.refresh_session()
                except Exception as e:
                    logger.error(f"Session refresh failed: {e}")
                    break
            else:
                logger.error(
                    "Session still stale after refresh attempts; "
                    "skipping this cycle."
                )

        # Out of attempts (or refresh failed): record the unknown state without
        # sending bogus notifications.
        for product, _, _ in results:
            self.state_manager.update_state(
                sku=product.sku, availability="unknown", notified=False
            )
        self.state_manager.save_state()

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
