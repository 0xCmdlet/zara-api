"""Configuration loader for Zara availability checker"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from .models import Product, ProductsConfig


class EnvConfig(BaseModel):
    """Environment configuration model"""
    zara_user_agent: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    email_to: str
    check_interval: int = 300
    log_level: str = "INFO"


def load_env_config() -> EnvConfig:
    """Load and validate environment configuration from .env file"""
    load_dotenv()

    try:
        config = EnvConfig(
            zara_user_agent=os.getenv("ZARA_USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "465")),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_from=os.getenv("EMAIL_FROM", ""),
            email_to=os.getenv("EMAIL_TO", ""),
            check_interval=int(os.getenv("CHECK_INTERVAL", "300")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

        # Validate required fields
        if not config.smtp_host:
            raise ValueError("SMTP_HOST is required in .env file")
        if not config.smtp_username:
            raise ValueError("SMTP_USERNAME is required in .env file")
        if not config.smtp_password:
            raise ValueError("SMTP_PASSWORD is required in .env file")
        if not config.email_from:
            raise ValueError("EMAIL_FROM is required in .env file")
        if not config.email_to:
            raise ValueError("EMAIL_TO is required in .env file")

        return config

    except ValidationError as e:
        raise ValueError(f"Invalid environment configuration: {e}")
    except ValueError as e:
        raise ValueError(f"Configuration error: {e}")


def load_products(config_path: Optional[str] = None) -> list[Product]:
    """Load and validate products from products.json"""
    if config_path is None:
        config_path = "products.json"

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Products configuration file not found: {config_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        config = ProductsConfig(**data)

        if not config.products:
            raise ValueError("No products defined in configuration file")

        return config.products

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in products configuration: {e}")
    except ValidationError as e:
        raise ValueError(f"Invalid products configuration: {e}")
