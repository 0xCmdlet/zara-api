"""CSV logger for product availability events"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Product, SkuAvailability


class CsvLogger:
    """Log product availability events to CSV file"""

    def __init__(self, csv_file: str = "availability_log.csv"):
        self.csv_file = Path(csv_file)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create CSV file with headers if it doesn't exist"""
        if not self.csv_file.exists():
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "product_name",
                    "size",
                    "sku",
                    "availability",
                    "product_link",
                ])

    def log_availability(
        self,
        product: Product,
        sku_availability: SkuAvailability,
    ) -> None:
        """
        Log product availability event to CSV

        Args:
            product: Product that became available
            sku_availability: SKU availability data
        """
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    product.name,
                    product.size,
                    sku_availability.sku,
                    sku_availability.availability,
                    str(product.link),
                ])
        except Exception as e:
            print(f"Error writing to CSV log: {e}")
