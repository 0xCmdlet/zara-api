"""Persistent store of known 'fake' SKUs returned by a stale Zara session.

When Zara's bot protection rejects a stale session it does not return an auth
error - it returns a default product whose SKUs never match the ones we track.
Those SKUs are recorded here so future cycles can recognise the fake response
immediately (and trigger a credential refresh) instead of treating it as real.
"""

import json
import logging
import os
from pathlib import Path
from typing import Iterable


logger = logging.getLogger(__name__)


class BannedSkuStore:
    """Tracks SKUs that have appeared in fake/stale API responses."""

    def __init__(self, store_file: str = "banned_skus.json"):
        self.store_file = Path(store_file)
        self.skus: set[int] = self._load()

    def _load(self) -> set[int]:
        if not self.store_file.exists():
            return set()
        try:
            with open(self.store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {int(s) for s in data}
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Could not read banned SKU store ({e}); starting empty")
            return set()

    def is_banned(self, sku: int) -> bool:
        return sku in self.skus

    def add(self, skus: Iterable[int]) -> set[int]:
        """Add SKUs to the ban list. Returns the set that was newly added."""
        incoming = {int(s) for s in skus}
        new = incoming - self.skus
        self.skus |= new
        return new

    def save(self) -> None:
        """Persist the ban list atomically."""
        temp_file = self.store_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(sorted(self.skus), f, indent=2)
            os.replace(temp_file, self.store_file)
        except Exception as e:
            logger.error(f"Error saving banned SKU store: {e}")
            if temp_file.exists():
                temp_file.unlink()
