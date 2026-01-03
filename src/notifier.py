"""Email notification sender via SMTP"""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .models import Product, SkuAvailability


logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications via SMTP"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        email_from: str,
        email_to: str,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.email_from = email_from
        self.email_to = email_to

    def _create_html_body(
        self,
        product: Product,
        sku_availability: SkuAvailability,
    ) -> str:
        """Create HTML email body"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Format status display
        status_display = {
            "in_stock": "IN STOCK ✓",
            "low_on_stock": "LOW ON STOCK ⚠️",
            "out_of_stock": "OUT OF STOCK"
        }.get(sku_availability.availability, sku_availability.availability.upper())

        html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #000;
            color: #fff;
            padding: 20px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
        }}
        .content {{
            padding: 30px 20px;
            background-color: #f9f9f9;
        }}
        .product-info {{
            margin: 20px 0;
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
        }}
        .label {{
            font-weight: bold;
            color: #000;
        }}
        .value {{
            margin-left: 10px;
        }}
        .status {{
            color: #28a745;
            font-weight: bold;
            font-size: 18px;
        }}
        .button {{
            display: inline-block;
            padding: 12px 30px;
            background-color: #000;
            color: #fff;
            text-decoration: none;
            border-radius: 4px;
            margin: 20px 0;
            font-weight: bold;
        }}
        .button:hover {{
            background-color: #333;
        }}
        .warning {{
            font-size: 13px;
            color: #856404;
            background-color: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 10px;
            border-radius: 4px;
            margin-top: 20px;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            font-size: 12px;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ZARA Product Available!</h1>
        </div>
        <div class="content">
            <p>Good news! The product you're tracking is now available:</p>
            <div class="product-info">
                <p><span class="label">Product:</span><span class="value">{product.name}</span></p>
                <p><span class="label">Size:</span><span class="value">{product.size}</span></p>
                <p><span class="label">SKU:</span><span class="value">{sku_availability.sku}</span></p>
                <p><span class="label">Status:</span><span class="value status">{status_display}</span></p>
                <p><span class="label">Checked at:</span><span class="value">{timestamp}</span></p>
            </div>
            <center>
                <a href="{product.link}" class="button">View Product on Zara</a>
            </center>
            <div class="warning">
                ⚠️ <strong>Note:</strong> {'Limited quantities available - ' if sku_availability.availability == 'low_on_stock' else ''}Availability may change quickly. Act fast!
            </div>
        </div>
        <div class="footer">
            <p>Automated notification from Zara Availability Checker</p>
        </div>
    </div>
</body>
</html>"""
        return html

    def send_notification(
        self,
        product: Product,
        sku_availability: SkuAvailability,
    ) -> bool:
        """
        Send email notification

        Args:
            product: Product that became available
            sku_availability: SKU availability data

        Returns:
            True if sent successfully, False otherwise
        """
        # Create subject based on availability status
        if sku_availability.availability == "low_on_stock":
            subject = f"[ZARA] {product.name} - Size {product.size} LOW ON STOCK!"
        else:
            subject = f"[ZARA] {product.name} - Size {product.size} NOW AVAILABLE!"

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        # Create HTML body
        html_body = self._create_html_body(product, sku_availability)
        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)

        # Send email with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Sending email notification for {product.name} "
                    f"(SKU: {sku_availability.sku}, attempt {attempt + 1}/{max_retries})"
                )

                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)

                logger.info(
                    f"Email sent successfully for {product.name} (SKU: {sku_availability.sku})"
                )
                return True

            except smtplib.SMTPAuthenticationError as e:
                logger.error(f"SMTP authentication failed: {e}")
                return False  # Don't retry auth errors

            except smtplib.SMTPException as e:
                logger.error(f"SMTP error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return False

            except Exception as e:
                logger.error(f"Unexpected error sending email (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return False

        return False
