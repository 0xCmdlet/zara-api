"""Data models for the Mango availability checker.

Mango's stock endpoint returns a simple availability boolean per size:

    {"colors": {"<colorId>": {"sizes": {"<sizeId>": {"available": false}}}}}

so a tracked item is identified by (product_id, color_id, size_id).
"""

from typing import Optional

from pydantic import BaseModel


class MangoProduct(BaseModel):
    """A single Mango size to track.

    Only ``product_id``, ``color_id`` and ``size_id`` are required - everything
    else has a sensible default. Those three aren't boilerplate: they're the
    exact product/colorway/size keys from Mango's stock response and define
    what's being watched.
    """

    product_id: str
    color_id: str
    size_id: str
    name: Optional[str] = None
    link: Optional[str] = None
    country_iso: str = "DE"
    channel_id: str = "shop"
    size_label: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Human label for emails/CSV (falls back to the product id)."""
        return self.name or f"Mango {self.product_id} ({self.color_id}/{self.size_id})"

    @property
    def endpoint(self) -> str:
        """The stock API URL for this product."""
        return (
            "https://online-orchestrator.mango.com/v3/stock/products"
            f"?countryIso={self.country_iso}"
            f"&channelId={self.channel_id}"
            f"&productId={self.product_id}"
        )

    @property
    def key(self) -> str:
        """Stable unique key for state tracking (sizeIds aren't globally unique)."""
        return f"{self.product_id}-{self.color_id}-{self.size_id}"


class MangoProductsConfig(BaseModel):
    """mango_products.json file model."""

    products: list[MangoProduct]
