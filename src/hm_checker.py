"""H&M availability checker orchestration.

Runs each product's availability lookup through the shared Akamai-authenticated
browser session (H&M sits behind Akamai, like Zara), matches the tracked SKUs
against the returned ``availability`` / ``fewPieceLeft`` lists, and notifies on a
transition into stock. Reuses ``EmailNotifier`` / ``CsvLogger`` and the generic
string-keyed state manager.
"""

import asyncio
import logging

from .browser_session import ApiError, AuthenticationError, BrowserSession
from .config import EnvConfig
from .csv_logger import CsvLogger
from .hm_models import HmProduct
from .mango_state import MangoStateManager
from .models import Product, SkuAvailability
from .notifier import EmailNotifier


logger = logging.getLogger(__name__)


class HmChecker:
    """Orchestrates H&M availability checks and notifications."""

    def __init__(
        self,
        products: list[HmProduct],
        env_config: EnvConfig,
        session: BrowserSession,
        state: MangoStateManager,
        delay_between: float = 5.0,
        dry_run: bool = False,
    ):
        self.products = products
        self.session = session
        self.state = state
        self.delay_between = delay_between
        self.dry_run = dry_run

        self.notifier = EmailNotifier(
            smtp_host=env_config.smtp_host,
            smtp_port=env_config.smtp_port,
            smtp_username=env_config.smtp_username,
            smtp_password=env_config.smtp_password,
            email_from=env_config.email_from,
            email_to=env_config.hm_email_to or env_config.email_to,
            admin_email=env_config.admin_email,
        )
        self.csv_logger = CsvLogger("hm_availability_log.csv")

    @staticmethod
    def _status_for(sku: str, availability: set[str], few: set[str]) -> str:
        if sku in few:
            return "low_on_stock"
        if sku in availability:
            return "in_stock"
        return "out_of_stock"

    def _notify(
        self, product: HmProduct, status: str, size_label: str, rep_sku: str
    ) -> bool:
        """Send an availability notification (or log it under --dry-run)."""
        adapted = Product(
            name=product.display_name,
            link=product.link or product.endpoint,
            api_endpoint=product.endpoint,
            size=size_label,
            sku=int(rep_sku) if rep_sku.isdigit() else 0,
        )
        avail = SkuAvailability(sku=adapted.sku, availability=status)  # type: ignore[arg-type]
        if self.dry_run:
            logger.info(
                f"[dry-run] would notify for {product.product_id} ({status}, {size_label})"
            )
            return True
        sent = self.notifier.send_notification(adapted, avail)
        if sent:
            self.csv_logger.log_availability(adapted, avail)
        return sent

    def _process_specific(self, product: HmProduct, availability: set, few: set) -> None:
        """Notify per tracked SKU (specific-size mode)."""
        for sku in product.skus:
            status = self._status_for(sku, availability, few)
            available = status in ("in_stock", "low_on_stock")
            key = f"{product.product_id}-{sku}"
            notify = self.state.should_notify(key, available)
            logger.info(f"{key} ({product.display_name}): {status} (notify: {notify})")
            notified = False
            if notify:
                notified = self._notify(product, status, sku, sku)
                if notified and not self.dry_run:
                    logger.info(f"Notification sent for {key}")
            self.state.update(key, available, notified=notified)

    def _process_any(self, product: HmProduct, availability: set, few: set) -> None:
        """Notify when *any* size comes back (watch-any mode)."""
        available_skus = sorted(availability | few)
        available = bool(available_skus)
        status = "in_stock" if availability else ("low_on_stock" if few else "out_of_stock")
        key = f"{product.product_id}-any"
        notify = self.state.should_notify(key, available)
        logger.info(
            f"{key} ({product.display_name}): {status}, "
            f"{len(available_skus)} sku(s) available (notify: {notify})"
        )
        notified = False
        if notify:
            size_label = f"{len(available_skus)} size(s): {', '.join(available_skus)}"
            notified = self._notify(product, status, size_label, available_skus[0])
            if notified and not self.dry_run:
                logger.info(f"Notification sent for {key}")
        self.state.update(key, available, notified=notified)

    async def _fetch(self, product: HmProduct) -> dict | None:
        """Fetch a product's availability JSON, refreshing the session once on 403."""
        try:
            return await self.session.fetch_json(product.endpoint)
        except AuthenticationError as e:
            logger.warning(f"{product.product_id}: {e}; renewing session and retrying")
            try:
                await self.session.refresh_session()
                return await self.session.fetch_json(product.endpoint)
            except Exception as e2:
                logger.error(f"{product.product_id}: still blocked after refresh: {e2}")
                return None
        except ApiError as e:
            logger.error(f"{product.product_id}: {e}")
            return None

    async def check_once(self) -> None:
        """Check every tracked product once, sequentially with a delay between."""
        logger.info(f"Checking {len(self.products)} H&M product(s)")
        for i, product in enumerate(self.products):
            data = await self._fetch(product)

            if data is None:
                keys = (
                    [f"{product.product_id}-any"]
                    if product.watch_any
                    else [f"{product.product_id}-{sku}" for sku in product.skus]
                )
                for key in keys:
                    self.state.update(key, None, notified=False)
            else:
                availability = set(data.get("availability", []))
                few = set(data.get("fewPieceLeft", []))
                if product.watch_any:
                    self._process_any(product, availability, few)
                else:
                    self._process_specific(product, availability, few)

            self.state.save()

            if i < len(self.products) - 1:
                await asyncio.sleep(self.delay_between)

    async def run_continuous(self, interval_seconds: int) -> None:
        logger.info(
            f"Starting continuous H&M checking "
            f"(interval: {interval_seconds}s, delay between items: {self.delay_between}s)"
        )
        while True:
            await self.check_once()
            logger.info(f"Waiting {interval_seconds}s until next check...")
            await asyncio.sleep(interval_seconds)
