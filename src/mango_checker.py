"""Mango availability checker orchestration.

Checks each tracked size sequentially with a delay in between (polite, single
request per item), looping on a fixed interval. Reuses the existing
``EmailNotifier`` and ``CsvLogger`` by adapting each Mango product into the
``Product`` / ``SkuAvailability`` shape they expect.
"""

import logging
import time
from datetime import datetime
from typing import Optional

from .config import EnvConfig
from .csv_logger import CsvLogger
from .mango_client import MangoAccessDenied, MangoClient, MangoError
from .mango_models import MangoProduct
from .mango_state import MangoStateManager
from .models import Product, SkuAvailability
from .notifier import EmailNotifier


logger = logging.getLogger(__name__)


# Exponential cooldown applied when a non-200 / blocked response is seen.
_BACKOFF_SCHEDULE = [120, 240, 480]  # 2m -> 4m -> 8m (then capped at 8m)


class MangoChecker:
    """Orchestrates Mango availability checks and notifications."""

    def __init__(
        self,
        products: list[MangoProduct],
        env_config: EnvConfig,
        client: MangoClient,
        state: MangoStateManager,
        delay_between: float = 5.0,
    ):
        self.products = products
        self.client = client
        self.state = state
        self.delay_between = delay_between

        self.notifier = EmailNotifier(
            smtp_host=env_config.smtp_host,
            smtp_port=env_config.smtp_port,
            smtp_username=env_config.smtp_username,
            smtp_password=env_config.smtp_password,
            email_from=env_config.email_from,
            email_to=env_config.email_to,
            admin_email=env_config.admin_email,
        )
        self.csv_logger = CsvLogger("mango_availability_log.csv")

    def _as_product(self, product: MangoProduct) -> tuple[Product, SkuAvailability]:
        """Adapt a Mango product into the notifier/CSV's expected models."""
        sku = int(product.size_id) if product.size_id.isdigit() else 0
        adapted = Product(
            name=product.name,
            link=product.link or product.endpoint,
            api_endpoint=product.endpoint,
            size=product.size_label or product.size_id,
            sku=sku,
        )
        avail = SkuAvailability(sku=sku, availability="in_stock")
        return adapted, avail

    def _notify(self, product: MangoProduct) -> bool:
        adapted, avail = self._as_product(product)
        sent = self.notifier.send_notification(adapted, avail)
        if sent:
            self.csv_logger.log_availability(adapted, avail)
        return sent

    def check_once(self) -> tuple[bool, Optional[str]]:
        """Check every tracked size once, sequentially with a delay between.

        Returns ``(had_error, last_error)`` where ``had_error`` is True if any
        product returned a non-200 / blocked response, so the caller can apply a
        cooldown and alert the admin.
        """
        logger.info(f"Checking {len(self.products)} Mango product(s)")
        had_error = False
        last_error: Optional[str] = None
        for i, product in enumerate(self.products):
            try:
                available = self.client.is_available(product)
            except MangoAccessDenied as e:
                logger.warning(f"{product.key}: {e} (recording unknown, no notify)")
                available = None
                had_error = True
                last_error = f"{product.key}: {e}"
            except MangoError as e:
                logger.error(f"{product.key}: {e}")
                available = None
                had_error = True
                last_error = f"{product.key}: {e}"

            if available is None:
                self.state.update(product.key, None, notified=False)
            else:
                notify = self.state.should_notify(product.key, available)
                logger.info(
                    f"{product.key} ({product.name}): "
                    f"available={available} (notify: {notify})"
                )
                notified = False
                if notify:
                    notified = self._notify(product)
                    if notified:
                        logger.info(f"Notification sent for {product.key}")
                    else:
                        logger.error(f"Failed to send notification for {product.key}")
                self.state.update(product.key, available, notified=notified)

            self.state.save()

            # Space out requests to stay under Mango's rate limit.
            if i < len(self.products) - 1:
                time.sleep(self.delay_between)

        return had_error, last_error

    def _alert_admin(self, error_message: Optional[str], cooldown: int) -> None:
        """Email the admin that a non-200 / blocked response was received."""
        subject = "[MANGO CHECKER] Non-200 / blocked response received"
        body = (
            "The Mango availability checker received a non-200 / blocked "
            "response and is entering an exponential cooldown.\n\n"
            f"Error: {error_message or 'unknown'}\n"
            f"Time (UTC): {datetime.utcnow().isoformat()}Z\n"
            f"Cooldown before next attempt: {cooldown}s\n\n"
            "Backoff schedule: 2m -> 4m -> 8m (capped). This alert is sent once "
            "per error episode; it resets after a successful cycle."
        )
        self.notifier.send_admin_alert(subject, body)

    def run_continuous(self, interval_seconds: int) -> None:
        logger.info(
            f"Starting continuous Mango checking "
            f"(interval: {interval_seconds}s, delay between items: {self.delay_between}s)"
        )
        backoff_idx = 0
        in_error = False
        while True:
            had_error, last_error = self.check_once()

            if had_error:
                cooldown = _BACKOFF_SCHEDULE[min(backoff_idx, len(_BACKOFF_SCHEDULE) - 1)]
                # Alert the admin once per error episode, not every cycle.
                if not in_error:
                    self._alert_admin(last_error, cooldown)
                    in_error = True
                backoff_idx += 1
                logger.warning(
                    f"Error/blocked response detected; backing off {cooldown}s "
                    f"before retry (escalation step {backoff_idx})"
                )
                time.sleep(cooldown)
            else:
                if in_error:
                    logger.info("Recovered from error state; resuming normal interval")
                in_error = False
                backoff_idx = 0
                logger.info(f"Waiting {interval_seconds}s until next check...")
                time.sleep(interval_seconds)
