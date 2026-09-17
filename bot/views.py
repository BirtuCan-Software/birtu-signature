import asyncio
import json
import logging
import threading
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
)

from .bot_handlers import (
    start_command, add_sig_command, list_sigs_command, set_gemini_command, set_default_command,
    handle_incoming_message, handle_callback_query, inline_query_handler
)

logger = logging.getLogger(__name__)

# Dedicated persistent event loop running in a background thread.
# In WSGI environments (such as cPanel Phusion Passenger), each HTTP request
# executes in a thread whose event loop is created and destroyed per request.
# Keeping a persistent loop in a dedicated daemon thread prevents
# "RuntimeError: Event loop is closed" in python-telegram-bot / HTTPX connection pools.
_bot_loop = None
_bot_thread = None
_loop_lock = threading.Lock()


def get_bot_loop():
    global _bot_loop, _bot_thread
    with _loop_lock:
        if _bot_loop is None or not _bot_loop.is_running():
            _bot_loop = asyncio.new_event_loop()
            _bot_thread = threading.Thread(target=_bot_loop.run_forever, daemon=True, name="TelegramBotLoop")
            _bot_thread.start()
        return _bot_loop


def run_in_bot_loop(coro, timeout=30):
    loop = get_bot_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


bot_app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

bot_app.add_handler(CommandHandler("start", start_command))
bot_app.add_handler(CommandHandler("add_sig", add_sig_command))
bot_app.add_handler(CommandHandler("list_sigs", list_sigs_command))
bot_app.add_handler(CommandHandler("set_gemini", set_gemini_command))
bot_app.add_handler(CommandHandler("set_default", set_default_command))

bot_app.add_handler(CallbackQueryHandler(handle_callback_query))
bot_app.add_handler(InlineQueryHandler(inline_query_handler))

bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming_message))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling Telegram update: %s", context.error, exc_info=context.error)


bot_app.add_error_handler(error_handler)


@csrf_exempt
def telegram_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))

            async def _process_update():
                if not bot_app._initialized:
                    await bot_app.initialize()
                update = Update.de_json(payload, bot_app.bot)
                await bot_app.process_update(update)

            run_in_bot_loop(_process_update())
            return JsonResponse({"status": "ok"})
        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            return JsonResponse({"status": "error"}, status=500)

    return JsonResponse({"status": "invalid request"}, status=400)
