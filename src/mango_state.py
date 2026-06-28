"""State persistence for the Mango checker (keyed by product-color-size).

Mirrors the Zara StateManager's notification rule - only alert on a transition
*into* availability - but keys by the composite Mango key instead of an int SKU.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class MangoStateManager:
    """Tracks last-known availability per tracked Mango size."""

    def __init__(self, state_file: str = "mango_state.json"):
        self.state_file = Path(state_file)
        self.states: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                self.states = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Corrupted Mango state ({e}); starting fresh")
            self.states = {}

    def save(self) -> None:
        """Persist state atomically (temp file + replace)."""
        temp_file = self.state_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.states, f, indent=2)
            os.replace(temp_file, self.state_file)
        except Exception as e:
            logger.error(f"Error saving Mango state: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def should_notify(self, key: str, available: bool) -> bool:
        """Notify only when a size becomes available from unknown/out-of-stock."""
        if not available:
            return False
        prev = self.states.get(key, {}).get("last_status")
        return prev in (None, "unknown", "out_of_stock")

    def update(
        self,
        key: str,
        available: Optional[bool],
        notified: bool = False,
    ) -> None:
        if available is None:
            status = "unknown"
        elif available:
            status = "in_stock"
        else:
            status = "out_of_stock"

        now = datetime.utcnow().isoformat() + "Z"
        entry = self.states.get(key, {})
        entry["last_status"] = status
        entry["last_checked"] = now
        if notified:
            entry["last_notified"] = now
        self.states[key] = entry
