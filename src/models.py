"""Data models for Zara product availability checker"""

from typing import Literal, Optional
from pydantic import BaseModel, HttpUrl


class Product(BaseModel):
    """Product configuration model"""
    name: str
    link: HttpUrl
    api_endpoint: HttpUrl
    size: str
    sku: int


class SkuAvailability(BaseModel):
    """SKU availability from API response"""
    sku: int
    availability: Literal["in_stock", "out_of_stock", "low_on_stock"]


class ApiResponse(BaseModel):
    """Zara API response model"""
    skusAvailability: list[SkuAvailability]


class ProductState(BaseModel):
    """Product state tracking model"""
    sku: int
    last_status: Literal["in_stock", "out_of_stock", "low_on_stock", "unknown"]
    last_checked: str  # ISO timestamp
    last_notified: Optional[str] = None  # ISO timestamp


class ProductsConfig(BaseModel):
    """Products configuration file model"""
    products: list[Product]
