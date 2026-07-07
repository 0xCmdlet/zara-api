"""Data models for the H&M availability checker.

H&M's availability endpoint returns two flat SKU lists:

    {"availability": ["1357966001002", ...], "fewPieceLeft": [...]}

- a SKU in ``availability``  -> in stock
- a SKU in ``fewPieceLeft``  -> low on stock
- otherwise                  -> out of stock

Each tracked product lists the ``skus`` we care about and matches them against
those returned lists.
"""

from typing import Optional

from pydantic import BaseModel


class HmProduct(BaseModel):
    """A single H&M product whose SKUs we track."""

    product_id: str
    # SKUs to watch. Leave empty to watch the whole product and notify as soon
    # as *any* size comes back in stock (useful for fully sold-out products
    # whose SKUs you don't know yet).
    skus: list[str] = []
    name: Optional[str] = None
    link: Optional[str] = None
    country: str = "de"

    @property
    def watch_any(self) -> bool:
        return not self.skus

    @property
    def endpoint(self) -> str:
        """The availability API URL for this product."""
        return (
            "https://ofg.hm.com/pdh-availability/v1/product/"
            f"{self.country}/availability/{self.product_id}"
        )

    @property
    def display_name(self) -> str:
        return self.name or f"H&M {self.product_id}"


class HmProductsConfig(BaseModel):
    """hm_products.json file model."""

    products: list[HmProduct]
