"""Minimal HTTP client for Mango's stock endpoint.

Unlike Zara, Mango's stock API answers a plain ``GET`` with JSON - no Akamai
browser session required. One request per check keeps us well under the WAF's
rate limit (bursts trigger an "Access Denied" IP block).
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from .mango_models import MangoProduct


logger = logging.getLogger(__name__)


class MangoError(Exception):
    """Base error fetching Mango stock."""


class MangoAccessDenied(MangoError):
    """The WAF blocked the request (403 / Access Denied) - back off."""


class MangoClient:
    """Performs one stock lookup per call via the JSON endpoint."""

    def __init__(self, user_agent: str, timeout: int = 30):
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self, product: MangoProduct) -> dict:
        """GET the raw stock JSON for a product."""
        req = urllib.request.Request(
            product.endpoint,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "de-DE,de;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            if e.code in (401, 403) or "Access Denied" in body:
                raise MangoAccessDenied(
                    f"Blocked by Mango WAF (status {e.code}); slow down."
                )
            raise MangoError(f"HTTP {e.code} for {product.key}: {body[:200]}")
        except urllib.error.URLError as e:
            raise MangoError(f"Network error for {product.key}: {e.reason}")

        if "Access Denied" in body:
            raise MangoAccessDenied("Blocked by Mango WAF (Access Denied); slow down.")

        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise MangoError(f"Invalid JSON for {product.key}: {e}")

    def is_available(self, product: MangoProduct) -> Optional[bool]:
        """Return availability for the tracked size.

        ``None`` means the color/size wasn't present in the response (treated as
        an unknown state, never a notification).
        """
        data = self.fetch(product)
        color = data.get("colors", {}).get(product.color_id)
        if not color:
            logger.warning(
                f"Color {product.color_id} not in response for {product.key}"
            )
            return None
        size = color.get("sizes", {}).get(product.size_id)
        if size is None:
            logger.warning(
                f"Size {product.size_id} not in response for {product.key}"
            )
            return None
        return bool(size.get("available"))
