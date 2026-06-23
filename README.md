# Zara Product Availability Checker

Monitor Zara products and get email notifications when they're back in stock.

## Features

- Track multiple products concurrently
- Email notifications on availability changes
- CSV log of all availability events
- Configurable check intervals
- State persistence (no duplicate notifications)
- Detailed logging
- Easy JSON configuration

## Requirements

- Python 3.10+
- SMTP email account (Gmail, Outlook, etc.)

## Installation

1. Clone the repository:
```bash
cd /Users/niklas/projects/private/zara-api
```

2. Activate virtual environment:
```bash
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install the Playwright browser (used to auto-fetch the Zara token/cookies):
```bash
playwright install chromium
# on a fresh Linux VPS, also pull in the browser's system libraries:
playwright install-deps chromium
```

The browser runs **headless by default**, so no display is needed on a VPS —
just `python -m src.main`. If Akamai starts blocking the headless session, set
`BROWSER_HEADLESS=false` in `.env` and run headful under a virtual display:
```bash
sudo apt-get install -y xvfb
xvfb-run -a python -m src.main
```

## How it works (no token needed)

Zara's availability API is protected by Akamai Bot Manager, which rejects plain
HTTP clients (even with a copied token/cookies) and serves a default "fake"
product instead. The key finding: the availability endpoint authenticates off a
**real browser's session cookies alone** — no bearer token required.

So the checker keeps **one real Google Chrome session alive** (via Playwright)
and runs each availability lookup as an in-browser
`fetch(..., {credentials: 'include'})` from a zara.com page, reading the JSON
straight back. There are no tokens or cookies to copy from DevTools anymore.

- On startup it opens Chrome, navigates to a product page to establish a valid
  session, and reuses that session for every check.
- If a stale/blocked session is detected (Zara returns a default "fake" product
  whose SKUs never match the ones you track), those SKUs are added to
  `banned_skus.json`, the session is renewed (re-navigated to refresh the Akamai
  cookies), and the check is retried automatically.

**Why real Chrome?** Akamai blocks Playwright's *bundled* Chromium even headless,
but lets real Google Chrome (`BROWSER_CHANNEL=chrome`) through, including
headless. Chrome must be installed on the host (see installation step 4).

## Configuration

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Zara (no token/cookies needed - a real browser session handles auth)
ZARA_USER_AGENT=Mozilla/5.0 (Macintosh; ...) Chrome/143.0.0.0 Safari/537.36

# Browser session
BROWSER_HEADLESS=true
BROWSER_CHANNEL=chrome
# BROWSER_PROXY=http://user:pass@host:port   # only if a VPS IP gets blocked

# SMTP Configuration (uses SSL on port 465)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here

# Email Settings
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@example.com

# Application Settings
CHECK_INTERVAL=300
LOG_LEVEL=INFO
```

**No token or cookies to copy.** Authentication is handled entirely by the real
Chrome session (see "How it works" above) — just make sure Chrome is installed
(`playwright install chrome`).

**Gmail App Password:**
If using Gmail, create an App Password:
1. Go to Google Account settings
2. Security → 2-Step Verification
3. App passwords → Generate new
4. Use the generated password in `SMTP_PASSWORD`

### 2. Products Configuration

Edit `products.json` to add/remove products you want to track:

```json
{
  "products": [
    {
      "name": "Product Name",
      "link": "https://www.zara.com/...",
      "api_endpoint": "https://www.zara.com/itxrest/1/catalog/store/10705/product/id/PRODUCTID/availability",
      "size": "M",
      "sku": 450244943
    }
  ]
}
```

**Finding Product Details:**
1. Go to the Zara product page
2. Select your desired size
3. Open Developer Tools → Network tab
4. Look for the `availability` API request
5. Copy:
   - `api_endpoint`: The full URL
   - `sku`: From the response (the SKU you want to track)
   - `link`: The product page URL
   - `name`: Any descriptive name
   - `size`: The size label

## Usage

### Run Continuously

Check products every 5 minutes (or as configured in `.env`):

```bash
python -m src.main
```

### Run Once (Testing)

Check all products once and exit:

```bash
python -m src.main --once
```

### Custom Interval

Override the check interval:

```bash
python -m src.main --interval 600  # Check every 10 minutes
```

### Custom Config File

Use a different products configuration file:

```bash
python -m src.main --config my-products.json
```

### Custom Log Level

Set log verbosity:

```bash
python -m src.main --log-level DEBUG
```

## How It Works

1. **Concurrent Checking**: All products are checked in parallel using async HTTP requests
2. **State Tracking**: `state.json` tracks each SKU's last known availability
3. **Smart Notifications**: Sends email when status changes from `out_of_stock` → `in_stock` or `low_on_stock`
4. **CSV Logging**: Every availability event is logged to `availability_log.csv` with timestamp and details
5. **No Duplicates**: Won't send multiple emails for the same available status
6. **Error Handling**: Individual product failures don't stop other checks
7. **Graceful Shutdown**: Press Ctrl+C to stop, state is saved automatically

**Note**: Zara API can return three availability statuses:
- `in_stock`: Product is fully available
- `low_on_stock`: Product is available but limited quantities
- `out_of_stock`: Product is not available

You'll be notified when a product becomes available (either `in_stock` or `low_on_stock`).

## File Structure

```
zara-api/
├── .env                      # Your configuration (not in git)
├── .env.example              # Template
├── .gitignore
├── requirements.txt
├── README.md
├── products.json             # Products to track
├── state.json                # State tracking (auto-generated)
├── availability_log.csv      # CSV log of all availability events (auto-generated)
├── logs/
│   └── zara_checker.log     # Detailed logs
└── src/
    ├── __init__.py
    ├── main.py               # Entry point
    ├── models.py             # Data models
    ├── config.py             # Configuration loader
    ├── api_client.py         # Zara API client
    ├── state_manager.py      # State persistence
    ├── notifier.py           # Email sender
    ├── csv_logger.py         # CSV availability logger
    └── checker.py            # Main logic
```

## Troubleshooting

### Email not sending
- Check SMTP credentials in `.env`
- For Gmail, use an App Password, not your regular password
- Verify `SMTP_HOST` and `SMTP_PORT` are correct for your provider

### "Product not found" errors
- The Zara API endpoint may have changed
- Check if the product is still available on the website
- Verify the `api_endpoint` URL is correct

### `403 Access Denied` / no session
- Akamai blocked the browser. Make sure `BROWSER_CHANNEL=chrome` and that real
  Google Chrome is installed (`playwright install chrome`) — bundled Chromium is
  blocked.
- On a VPS, the datacenter IP may be flagged. Set `BROWSER_PROXY` to a
  residential proxy.

### SKU not found / all products return the same SKUs
- This is a stale/blocked session: Zara served a default "fake" product. The
  checker detects this automatically, bans those SKUs (`banned_skus.json`),
  renews the browser session, and retries.
- Verify each product's `sku` actually belongs to its `api_endpoint`'s product.
- Run with `--log-level DEBUG` to see which SKUs are returned.

## State Transitions

The checker only sends notifications on these transitions:

| Previous Status | Current Status | Notification |
|----------------|----------------|--------------|
| unknown        | in_stock       | ✅ Yes       |
| unknown        | low_on_stock   | ✅ Yes       |
| unknown        | out_of_stock   | ❌ No        |
| out_of_stock   | in_stock       | ✅ Yes       |
| out_of_stock   | low_on_stock   | ✅ Yes       |
| out_of_stock   | out_of_stock   | ❌ No        |
| in_stock       | in_stock       | ❌ No        |
| in_stock       | low_on_stock   | ❌ No        |
| in_stock       | out_of_stock   | ❌ No        |
| low_on_stock   | in_stock       | ❌ No        |
| low_on_stock   | low_on_stock   | ❌ No        |
| low_on_stock   | out_of_stock   | ❌ No        |

## CSV Availability Log

Every time a product becomes available (and an email notification is sent), the event is logged to `availability_log.csv`.

**CSV Format:**
```csv
timestamp,product_name,size,sku,availability,product_link
2026-01-03 14:30:15,Wool Coat,M,450244943,in_stock,https://www.zara.com/...
2026-01-03 15:45:22,Denim Jacket,L,450244945,low_on_stock,https://www.zara.com/...
```

**Columns:**
- `timestamp`: When the product became available (UTC)
- `product_name`: Name from products.json
- `size`: Size being tracked
- `sku`: The specific SKU number
- `availability`: Status (in_stock or low_on_stock)
- `product_link`: Direct link to the product

This CSV file is perfect for:
- Tracking historical availability patterns
- Analyzing which products/sizes become available most often
- Importing into Excel/Google Sheets for further analysis

## Logs

Logs are saved to `logs/zara_checker.log` with rotation:
- Max size: 10MB per file
- Keeps 5 backup files
- Detailed debug information

View logs in real-time:
```bash
tail -f logs/zara_checker.log
```

## Security Notes

- Never commit `.env` to git (already in `.gitignore`)
- Use app-specific passwords for email
- SMTP uses SSL encryption (port 465) for secure email transmission
- State file may contain product information

## Example Workflow

1. Find a product you want on Zara
2. Get the API endpoint and SKU from browser Developer Tools
3. Add it to `products.json`
4. Run `python -m src.main --once` to test
5. If working, run `python -m src.main` for continuous monitoring
6. You'll receive an email when the product becomes available

## License

MIT
