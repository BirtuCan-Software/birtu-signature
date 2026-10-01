# Birtu Signature Bot

A stateless Telegram Bot built with Django and python-telegram-bot (v20+). It appends formatted signatures with HTML/Markdown support to text messages, media, and documents.

Designed specifically to run reliably on shared hosting environments such as cPanel's "Setup Python App" via webhooks. The bot handles media albums, supports PyMySQL without requiring C compiler dependencies, features an isolated persistent event loop for WSGI servers, and integrates with Google Gemini for context-aware signatures via Bring-Your-Own-Key (BYOK).

---

## Features

- **Stateless Webhook Architecture:** Tailored for WSGI environments like Phusion Passenger on cPanel without background polling.
- **Persistent Async Loop:** Background event loop management prevents event loop teardown issues under WSGI servers.
- **Multi-Process Shared Cache:** File-based caching synchronizes incoming media and original message metadata across multiple server worker processes.
- **Media and Album Support:** Processes images, videos, documents, and media groups without duplicate signatures.
- **Inline Query Mode:** Append signatures directly inside any chat using `@YourBotUsername`.
- **Gemini AI Integration (BYOK):** Encrypted at-rest API key storage for generating contextual, instruction-driven signatures.
- **Default Signatures:** Automatic signature appending for routine messaging without manual menu navigation.
- **Pure-Python Database Compatibility:** Fully configured for PyMySQL to avoid native compile issues with mysqlclient on shared hosting.

---

## Prerequisites

- Python 3.10+
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Cloudflared (optional, for local webhook testing)
- cPanel with "Setup Python App" enabled or any WSGI/ASGI hosting provider

---

## Local Development Setup

### 1. Clone and Install Dependencies

```bash
git clone https://github.com/BirtuCan-Software/birtu-signature.git
cd birtu-signature

# Create and activate virtual environment
python -m venv venv

# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file in the project root:

```ini
DEBUG=True
SECRET_KEY=your-local-secret-key-change-in-production
DATABASE_URL=sqlite:///db.sqlite3
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GEMINI_MODEL=gemini-3.6-flash
```

### 3. Database Migrations

Apply database migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

### 4. Run Development Server

```bash
python manage.py runserver
```

The application will be running locally at `http://localhost:8000`.

---

## Setting Up Cloudflare Tunnel (Local Webhooks)

Telegram requires a publicly accessible HTTPS endpoint to send webhook events. You can use a free Cloudflare Quick Tunnel to test locally:

1. Install `cloudflared` on your system.
2. In a separate terminal window, start the tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. Copy the generated URL (e.g., `https://example-subdomain.trycloudflare.com`).
4. Register the webhook with Telegram using the management command:
   ```bash
   python manage.py set_webhook https://example-subdomain.trycloudflare.com
   ```

---

## Deployment to cPanel (Setup Python App)

cPanel serves Python web applications using Phusion Passenger via WSGI.

### 1. Create Application in cPanel

1. Log into your cPanel account.
2. Open **Setup Python App** and select **Create Application**.
3. Choose your Python version (3.10 or higher).
4. Set **Application root** (e.g., `birtu_bot`).
5. Set **Application URL** to your target domain or subdomain.
6. Set **Application startup file** to `passenger_wsgi.py`.
7. Set **Application Entry point** to `application`.
8. Click **Create**.

### 2. Deploy Files and Configure Environment

1. Package project files into a zip archive (excluding `venv`, `.git`, `.cache`, and `db.sqlite3`).
2. Upload and extract the archive into your application directory via cPanel File Manager.
3. In cPanel, navigate to **MySQL Databases** and create a database and database user.
4. Create or update your `.env` file in the application directory:
   ```ini
   DEBUG=False
   SECRET_KEY=generate-a-strong-random-secret-key
   DATABASE_URL=mysql://db_user:db_password@localhost:3306/db_name
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   GEMINI_MODEL=gemini-3.6-flash
   ```

### 3. Install Dependencies and Run Migrations

1. Open the cPanel Terminal.
2. Activate the virtual environment path provided at the top of the "Setup Python App" page:
   ```bash
   source /home/username/virtualenv/birtu_bot/3.11/bin/activate
   ```
3. Run migrations and collect static files:
   ```bash
   cd birtu_bot
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

### 4. Configure `passenger_wsgi.py`

Replace the default contents of `passenger_wsgi.py` with:

```python
import os
import sys

# Add project root directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

# Set Django settings module
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

# Import WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 5. Restart Application and Register Production Webhook

1. Return to **Setup Python App** in cPanel and click **Restart**.
2. Register your live webhook URL in the cPanel terminal:
   ```bash
   python manage.py set_webhook https://your-domain.com
   ```

---

## Bot Commands

Users interact with the bot using standard commands:

- `/start` - Initialize bot conversation and view instructions
- `/add_sig [Name] | [Signature Content]` - Save a new signature template
- `/del_sig [Name]` - Delete an existing signature (alias: `/delete_sig`)
- `/list_sigs` - Display all saved signatures
- `/set_default [Name]` - Assign a default signature (use `none` to disable)
- `/set_gemini [API_KEY]` - Save a personal Google Gemini API key for AI features

---

## Security

Personal Google Gemini API keys are encrypted at rest in the database using Fernet symmetric encryption derived from Django's `SECRET_KEY`. Keep your `SECRET_KEY` protected and never commit production `.env` files to source control.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details. Commercial use, modification, distribution, and private use are permitted.
