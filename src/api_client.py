"""Async API client for Zara availability endpoint"""

import logging
from typing import Optional

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .models import ApiResponse, Product


logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Base API error"""
    pass


class AuthenticationError(ApiError):
    """Authentication failed"""
    pass


class ProductNotFoundError(ApiError):
    """Product not found"""
    pass


class RateLimitError(ApiError):
    """Rate limit exceeded"""
    pass


class ZaraApiClient:
    """Async client for Zara availability API"""

    def __init__(self, api_token: str, user_agent: str):
        self.api_token = api_token
        self.user_agent = user_agent
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Create aiohttp session"""
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()

    def _get_headers(self, referer: str = None) -> dict:
        """Build request headers"""
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "User-Agent": self.user_agent,
            "sec-ch-ua-platform": '"macOS"',
            "sec-ch-ua": '"Chromium";v="143", "Not A(Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
        }

        if referer:
            headers["Referer"] = referer

        return headers

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, ApiError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        reraise=True,
    )
    async def check_availability(self, product: Product) -> ApiResponse:
        """
        Check product availability via Zara API

        Args:
            product: Product to check

        Returns:
            ApiResponse with SKU availability data

        Raises:
            AuthenticationError: Invalid or expired token
            ProductNotFoundError: Product not found
            RateLimitError: Rate limit exceeded
            ApiError: Other API errors
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use 'async with' context manager.")

        url = str(product.api_endpoint)
        headers = self._get_headers(referer=str(product.link))

        logger.debug(f"Checking availability for SKU {product.sku}: {url}")
        logger.debug(f"Request headers: {headers}")

        try:
            async with self.session.get(url, headers=headers) as response:
                # Handle different status codes
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"API Response for {product.sku}: {data}")
                    api_response = ApiResponse(**data)
                    logger.debug(
                        f"SKU {product.sku}: Got {len(api_response.skusAvailability)} SKUs"
                    )
                    # Log all SKUs in the response
                    for sku_avail in api_response.skusAvailability:
                        logger.debug(f"  - SKU {sku_avail.sku}: {sku_avail.availability}")
                    return api_response

                elif response.status in (401, 403):
                    logger.error(f"Authentication failed for SKU {product.sku}")
                    raise AuthenticationError(
                        f"Authentication failed: {response.status}"
                    )

                elif response.status == 404:
                    logger.warning(f"Product not found for SKU {product.sku}")
                    raise ProductNotFoundError(f"Product not found: {url}")

                elif response.status == 429:
                    retry_after = response.headers.get("Retry-After", "60")
                    logger.warning(
                        f"Rate limit exceeded for SKU {product.sku}. "
                        f"Retry after {retry_after}s"
                    )
                    raise RateLimitError(f"Rate limit exceeded. Retry after {retry_after}s")

                else:
                    error_text = await response.text()
                    logger.error(
                        f"API error for SKU {product.sku}: {response.status} - {error_text}"
                    )
                    raise ApiError(f"API error: {response.status} - {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Network error for SKU {product.sku}: {e}")
            raise ApiError(f"Network error: {e}")
        except Exception as e:
            if isinstance(e, (AuthenticationError, ProductNotFoundError, RateLimitError, ApiError)):
                raise
            logger.error(f"Unexpected error for SKU {product.sku}: {e}")
            raise ApiError(f"Unexpected error: {e}")
