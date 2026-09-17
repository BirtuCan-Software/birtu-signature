import asyncio
from django.core.management.base import BaseCommand
from django.conf import settings
from telegram.ext import Application

class Command(BaseCommand):
    help = 'Sets the Telegram bot webhook URL'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='The base URL of your Django app (e.g., https://yourdomain.com)')

    def handle(self, *args, **kwargs):
        base_url = kwargs['url'].rstrip('/')
        webhook_url = f"{base_url}/bot/webhook/"
        
        # Async helper to set webhook
        async def set_webhook():
            app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
            result = await app.bot.set_webhook(url=webhook_url)
            return result

        success = asyncio.run(set_webhook())
        
        if success:
            self.stdout.write(self.style.SUCCESS(f'Successfully set webhook to: {webhook_url}'))
        else:
            self.stdout.write(self.style.ERROR('Failed to set webhook.'))
