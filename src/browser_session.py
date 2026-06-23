"""Long-lived real-browser session for querying Zara availability.

Zara's availability API is protected by Akamai Bot Manager. A plain HTTP client
(even with a copied token + cookies) gets rejected and served a default "fake"
product. A *real* Google Chrome session, however, is accepted - and crucially the
availability endpoint authenticates off the browser's **session cookies alone**,
so no bearer token is needed at all.

This module keeps one Chrome session alive for the process lifetime and performs
each availability lookup as an in-browser ``fetch(..., {credentials:'include'})``
from a zara.com page, reading the JSON straight back. If the session goes stale
(Akamai serves a 403 or a fake product), :meth:`refresh_session` re-navigates to
the bootstrap page to renew the Akamai cookies.

Akamai blocks Playwright's *bundled* Chromium, so the default channel is real
``chrome`` (must be installed: ``playwright install chrome`` /
``google-chrome-stable``). On a flagged datacenter IP, route through a
residential proxy via ``proxy``.
"""

import json
import logging
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from .models import ApiResponse, Product


logger = logging.getLogger(__name__)


# Runs in the browser: fetch the endpoint with the page's own cookies and
# return the status + raw body so Python can parse/inspect it.
_FETCH_JS = """
async (endpoint) => {
    try {
        const r = await fetch(endpoint, {
            credentials: 'include',
            headers: {'Accept': 'application/json'},
        });
        return {status: r.status, body: await r.text()};
    } catch (e) {
        return {status: -1, body: String(e)};
    }
}
"""


class ApiError(Exception):
    """Base availability-fetch error."""


class AuthenticationError(ApiError):
    """Session rejected by Zara/Akamai (403/401 or Access Denied)."""


class BrowserSession:
    """A persistent real-Chrome session used to query availability."""

    def __init__(
        self,
        bootstrap_url: str,
        user_agent: str,
        headless: bool = True,
        timeout: int = 30,
        locale: str = "de-DE",
        channel: Optional[str] = "chrome",
        proxy: Optional[str] = None,
        settle_ms: int = 4000,
    ):
        self.bootstrap_url = bootstrap_url
        self.user_agent = user_agent
        self.headless = headless
        self.timeout = timeout
        self.locale = locale
        self.channel = channel or None
        self.proxy = proxy or None
        self.settle_ms = settle_ms

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        """Launch the browser and establish a valid Zara session."""
        logger.info(
            f"Starting browser session (channel={self.channel or 'chromium'}, "
            f"headless={self.headless}, proxy={'yes' if self.proxy else 'no'})"
        )
        self._pw = await async_playwright().start()
        self._browser = await self._launch(self._pw)
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            locale=self.locale,
        )
        # Mask the most obvious automation tells before any page script runs.
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self._page = await self._context.new_page()
        await self.refresh_session()

    async def refresh_session(self) -> None:
        """(Re)navigate to the bootstrap page to renew Akamai cookies."""
        if self._page is None:
            raise RuntimeError("Session not started. Call start() first.")
        logger.info(f"Establishing session via {self.bootstrap_url}")
        resp = await self._page.goto(
            self.bootstrap_url,
            wait_until="domcontentloaded",
            timeout=self.timeout * 1000,
        )
        status = resp.status if resp else None
        if status and status >= 400:
            raise AuthenticationError(
                f"Bootstrap navigation returned {status} - Akamai likely blocked "
                f"this session (try BROWSER_HEADLESS=false or a residential proxy)."
            )
        await self._accept_cookie_banner()
        # Let the Akamai JS challenge set its cookies before we query the API.
        await self._page.wait_for_timeout(self.settle_ms)

    async def check_availability(self, product: Product) -> ApiResponse:
        """Fetch one product's availability from inside the browser session."""
        if self._page is None:
            raise RuntimeError("Session not started. Call start() first.")

        endpoint = str(product.api_endpoint)
        logger.debug(f"In-browser fetch for SKU {product.sku}: {endpoint}")
        result = await self._page.evaluate(_FETCH_JS, endpoint)
        status = result.get("status")
        body = result.get("body", "")

        if status == 200:
            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                raise ApiError(f"Invalid JSON for SKU {product.sku}: {e}")
            return ApiResponse(**data)

        if status in (401, 403) or "Access Denied" in body:
            raise AuthenticationError(
                f"Session rejected for SKU {product.sku} (status {status})"
            )

        raise ApiError(
            f"Unexpected status {status} for SKU {product.sku}: {body[:200]}"
        )

    async def close(self) -> None:
        """Tear down the browser session."""
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()
        self._browser = self._context = self._page = self._pw = None

    async def _launch(self, p):
        """Launch the browser, preferring real Chrome with a Chromium fallback."""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        launch_kwargs = {"headless": self.headless, "args": args}
        if self.proxy:
            launch_kwargs["proxy"] = self._parse_proxy(self.proxy)

        if self.channel:
            try:
                return await p.chromium.launch(channel=self.channel, **launch_kwargs)
            except Exception as e:
                logger.warning(
                    f"Could not launch '{self.channel}' channel ({e}); falling "
                    f"back to bundled Chromium (likely to be blocked by Akamai)"
                )
        return await p.chromium.launch(**launch_kwargs)

    @staticmethod
    def _parse_proxy(proxy_url: str) -> dict:
        """Convert an http://user:pass@host:port URL to Playwright's proxy dict."""
        parsed = urlparse(proxy_url)
        server = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            server += f":{parsed.port}"
        proxy = {"server": server}
        if parsed.username:
            proxy["username"] = parsed.username
        if parsed.password:
            proxy["password"] = parsed.password
        return proxy

    async def _accept_cookie_banner(self) -> None:
        """Best-effort click on the OneTrust 'accept' button."""
        try:
            await self._page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            logger.debug("Accepted cookie consent banner")
        except Exception:
            pass  # Banner not present or already dismissed - not fatal.
