"""State management for tracking product availability"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from .models import ProductState


class StateManager:
    """Manages product availability state persistence"""

    def __init__(self, state_file: str = "state.json"):
        self.state_file = Path(state_file)
        self.states: Dict[int, ProductState] = {}
        self.load_state()

    def load_state(self) -> None:
        """Load state from JSON file"""
        if not self.state_file.exists():
            self.states = {}
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.states = {
                int(sku): ProductState(**state_data)
                for sku, state_data in data.items()
            }
        except (json.JSONDecodeError, ValueError) as e:
            # Backup corrupted file and start fresh
            backup_path = self.state_file.with_suffix(".json.backup")
            if self.state_file.exists():
                os.rename(self.state_file, backup_path)
            print(f"Warning: Corrupted state file backed up to {backup_path}. Starting fresh.")
            self.states = {}

    def save_state(self) -> None:
        """Save state to JSON file atomically"""
        # Convert states to dict for JSON serialization
        data = {
            str(sku): state.model_dump()
            for sku, state in self.states.items()
        }

        # Write to temp file first, then rename (atomic operation)
        temp_file = self.state_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Atomic rename
            os.replace(temp_file, self.state_file)
        except Exception as e:
            print(f"Error saving state: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def should_notify(self, sku: int, current_status: str) -> bool:
        """
        Determine if notification should be sent based on state transition

        Returns True only when:
        - Previous status was "unknown" (first check) and current is "in_stock" or "low_on_stock"
        - Previous status was "out_of_stock" and current is "in_stock" or "low_on_stock"

        Does NOT notify when:
        - Transitioning between "in_stock" and "low_on_stock" (both are available)
        - Current status is "out_of_stock"
        """
        if sku not in self.states:
            # First time checking this SKU - notify if available
            return current_status in ["in_stock", "low_on_stock"]

        last_status = self.states[sku].last_status

        # Only notify on transition to available (in_stock or low_on_stock) from unavailable
        return (
            current_status in ["in_stock", "low_on_stock"]
            and last_status in ["out_of_stock", "unknown"]
        )

    def update_state(
        self,
        sku: int,
        availability: str,
        notified: bool = False
    ) -> None:
        """Update state for a SKU"""
        now = datetime.utcnow().isoformat() + "Z"

        if sku in self.states:
            # Update existing state
            self.states[sku].last_status = availability  # type: ignore
            self.states[sku].last_checked = now
            if notified:
                self.states[sku].last_notified = now
        else:
            # Create new state
            self.states[sku] = ProductState(
                sku=sku,
                last_status=availability,  # type: ignore
                last_checked=now,
                last_notified=now if notified else None,
            )

    def get_state(self, sku: int) -> ProductState | None:
        """Get state for a SKU"""
        return self.states.get(sku)
