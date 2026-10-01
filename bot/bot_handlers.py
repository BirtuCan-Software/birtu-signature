import html
import logging
import re
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes
from django.conf import settings
from django.core.cache import cache
from .models import TelegramUser, Signature

logger = logging.getLogger(__name__)

async def get_or_create_user(telegram_user):
    user, _ = await TelegramUser.objects.aget_or_create(
        telegram_id=telegram_user.id,
        defaults={
            'username': telegram_user.username,
            'first_name': telegram_user.first_name,
            'last_name': telegram_user.last_name,
        }
    )
    return user

# --- COMMAND HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_or_create_user(update.effective_user)
    await update.message.reply_text(
        f"Hello {user.first_name}! 🌟\n\n"
        "Send me a message or media, and I'll append your signature.\n\n"
        "Commands:\n"
        "/add_sig [Name] | [Your Signature Content]\n"
        "/del_sig [Name] - Delete a signature\n"
        "/list_sigs - View signatures\n"
        "/set_default [Name] - Auto-apply a signature\n"
        "/set_gemini [API_KEY] - Set your AI key for auto-generations"
    )

async def add_sig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use text_html so entities (custom emojis, links, bold, italics) are converted to HTML tags
    full_html = update.message.text_html
    
    # Strip the command prefix (/add_sig or /add_sig@YourBot)
    text = re.sub(r'^/add_sig(?:@\w+)?\s*', '', full_html, flags=re.IGNORECASE).strip()
    
    if '|' not in text:
        await update.message.reply_text("⚠️ Format error. Use:\n/add_sig MySig | This is my signature text!")
        return
        
    name, content = text.split('|', 1)
    name = name.strip()
    content = content.strip()
    
    user = await get_or_create_user(update.effective_user)
    
    if await Signature.objects.filter(user=user, name=name).aexists():
        await update.message.reply_text("A signature with this name already exists.")
        return
        
    await Signature.objects.acreate(user=user, name=name, content=content)
    await update.message.reply_text(f"✅ Signature '{name}' saved with rich formatting!")

async def delete_sig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Strip the command prefix (/del_sig, /delete_sig, or with @YourBot)
    name = re.sub(r'^/(?:del_sig|delete_sig)(?:@\w+)?\s*', '', update.message.text, flags=re.IGNORECASE).strip()
    user = await get_or_create_user(update.effective_user)
    
    if not name:
        sigs = [sig.name async for sig in Signature.objects.filter(user=user)]
        if sigs:
            names_list = "\n".join([f"• <code>{html.escape(s)}</code>" for s in sigs])
            await update.message.reply_text(
                f"⚠️ Please specify which signature to delete.\nUse format: /del_sig [Name]\n\nYour signatures:\n{names_list}",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("You have no signatures to delete.")
        return

    try:
        sig = await Signature.objects.aget(user=user, name__iexact=name)
        sig_name = sig.name
        if user.default_signature_id == sig.id:
            user.default_signature = None
            await user.asave()
        await sig.adelete()
        await update.message.reply_text(f"🗑️ Signature '{sig_name}' deleted successfully.")
    except Signature.DoesNotExist:
        await update.message.reply_text(f"❌ Signature '{name}' not found.")

del_sig_command = delete_sig_command

async def list_sigs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_or_create_user(update.effective_user)
    sigs = [sig async for sig in Signature.objects.filter(user=user)]
    if not sigs:
        await update.message.reply_text("You have no signatures. Use /add_sig to create one.")
        return
    
    msg = "📝 <b>Your Signatures:</b>\n\n"
    for sig in sigs:
        msg += f"🔹 <b>{html.escape(sig.name)}</b>\n{sig.content}\n\n"
    try:
        await update.message.reply_text(msg, parse_mode='HTML')
    except Exception:
        await update.message.reply_text(msg)

async def set_gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.replace('/set_gemini', '').strip()
    if not key:
        await update.message.reply_text("⚠️ Use format: /set_gemini AIzaSyYourApiKeyHere...")
        return
    user = await get_or_create_user(update.effective_user)
    user.gemini_api_key = key
    await user.asave()
    await update.message.reply_text("✅ Gemini API Key saved securely! You can now use the 🤖 AI Generate button.")

async def set_default_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.replace('/set_default', '').strip()
    user = await get_or_create_user(update.effective_user)
    if not name:
        await update.message.reply_text("⚠️ Use format: /set_default [Signature Name]\nTo disable, use: /set_default none")
        return
    
    if name.lower() == 'none':
        user.default_signature = None
        await user.asave()
        await update.message.reply_text("✅ Default signature disabled.")
        return

    try:
        sig = await Signature.objects.aget(user=user, name__iexact=name)
        user.default_signature = sig
        await user.asave()
        await update.message.reply_text(f"✅ Default signature set to '{sig.name}'. It will now be appended automatically.")
    except Signature.DoesNotExist:
        await update.message.reply_text("❌ Signature not found.")

# --- MESSAGE PROCESSING ---

async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = await get_or_create_user(update.effective_user)
    
    if update.message.reply_to_message and "[MsgID:" in update.message.reply_to_message.text:
        match = re.search(r'\[MsgID: (\d+)\]', update.message.reply_to_message.text)
        if match:
            orig_msg_id = int(match.group(1))
            instruction = update.message.text
            await process_ai_generation(update, context, user, orig_msg_id, instruction)
            return

    if update.message.media_group_id:
        cache_key = f"media_group_{update.message.media_group_id}"
        if cache.get(cache_key): return
        cache.set(cache_key, True, timeout=60)

    is_media = bool(
        update.message.photo or update.message.video or update.message.document
        or update.message.audio or update.message.voice or update.message.animation
    )
    content_text = update.message.text or update.message.caption or ("Media/File" if is_media else "")
    content_html = update.message.text_html or update.message.caption_html or ("Media/File" if is_media else "")

    cache.set(f"msg_text_{update.message.message_id}", content_text, timeout=3600)
    cache.set(f"msg_html_{update.message.message_id}", content_html, timeout=3600)
    cache.set(f"msg_is_media_{update.message.message_id}", is_media, timeout=3600)
    if is_media and update.message.caption:
        cache.set(f"msg_caption_{update.message.message_id}", update.message.caption, timeout=3600)
        cache.set(f"msg_caption_html_{update.message.message_id}", update.message.caption_html, timeout=3600)

    if user.default_signature_id:
        sig = await Signature.objects.aget(id=user.default_signature_id)
        await copy_and_append_signature(update, context, update.message, sig.content)
        return

    sigs = [sig async for sig in Signature.objects.filter(user=user)]
    if not sigs:
        await update.message.reply_text("You don't have any signatures yet! Use /add_sig")
        return

    keyboard = [[InlineKeyboardButton(sig.name, callback_data=f"sig:{sig.id}:{update.message.message_id}")] for sig in sigs]
    keyboard.append([InlineKeyboardButton("🤖 Generate AI Signature", callback_data=f"ai:{update.message.message_id}")])
    
    await update.message.reply_text("👇 Pick a signature to append:", reply_to_message_id=update.message.message_id, reply_markup=InlineKeyboardMarkup(keyboard))

# --- CALLBACK & AI GENERATION LOGIC ---

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await get_or_create_user(update.effective_user)

    if query.data.startswith("ai:"):
        msg_id = query.data.split(':')[1]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🤖 What is your instruction for the AI? (e.g., 'Summarize and add hashtags')\n\n[MsgID: {msg_id}]",
            reply_markup=ForceReply(selective=True)
        )
        await query.message.delete()
        return

    if query.data.startswith("sig:"):
        _, sig_id, msg_id = query.data.split(':')
        try:
            signature = await Signature.objects.aget(id=int(sig_id), user=user)
            original_msg = query.message.reply_to_message
            await copy_and_append_signature(update, context, original_msg, signature.content, int(msg_id))
            await query.message.delete()
        except Signature.DoesNotExist:
            await query.edit_message_text("Signature not found.")

async def process_ai_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, user, orig_msg_id, instruction):
    if not user.gemini_api_key:
        await update.message.reply_text("❌ Please set your Gemini API key first using /set_gemini")
        return
        
    orig_text = cache.get(f"msg_text_{orig_msg_id}")
    if not orig_text:
        await update.message.reply_text("⚠️ Original message expired or not found. Please send your message again.")
        return

    is_media = cache.get(f"msg_is_media_{orig_msg_id}")
    if is_media is None:
        is_media = (orig_text == "Media/File")

    await update.message.reply_text("🤖 Generating signature...")
    
    try:
        client = genai.Client(api_key=user.gemini_api_key)
        prompt = (
            f"Original Message:\n\"{orig_text}\"\n\n"
            f"Instruction: {instruction}\n\n"
            "Return ONLY the generated signature text to append. Do not include quotes or conversational filler."
        )
        
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-3.6-flash')
        config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        logger.info("Requesting Gemini completion for msg_id=%s with model=%s", orig_msg_id, model_name)
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        ai_signature = (response.text or "").strip()
        logger.info("AI generated signature for msg_id=%s: %r", orig_msg_id, ai_signature)

        if not ai_signature:
            await update.message.reply_text("⚠️ Gemini returned an empty response. Please try with a different instruction.")
            return

        if is_media:
            orig_caption = cache.get(f"msg_caption_{orig_msg_id}") or (orig_text if orig_text != "Media/File" else "")
            orig_caption_html = cache.get(f"msg_caption_html_{orig_msg_id}") or orig_caption
            dummy_msg = type('obj', (object,), {
                'text': None,
                'text_html': None,
                'caption': orig_caption,
                'caption_html': orig_caption_html,
                'message_id': orig_msg_id,
            })()
        else:
            orig_html = cache.get(f"msg_html_{orig_msg_id}") or orig_text
            dummy_msg = type('obj', (object,), {
                'text': orig_text,
                'text_html': orig_html,
                'caption': None,
                'caption_html': None,
                'message_id': orig_msg_id,
            })()

        await copy_and_append_signature(update, context, dummy_msg, ai_signature, orig_msg_id)
        
    except Exception as e:
        logger.error(f"AI Error: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to generate AI signature. Check your API key or prompt.")

async def copy_and_append_signature(update: Update, context, original_msg, signature_content, explicit_msg_id=None):
    chat_id = update.effective_chat.id
    msg_id = explicit_msg_id or getattr(original_msg, 'message_id', None)

    # Check whether the message is media or pure text
    is_media = (
        getattr(original_msg, 'caption', None) is not None
        or (original_msg and not getattr(original_msg, 'text', None))
        or cache.get(f"msg_is_media_{msg_id}") is True
    )

    if not is_media:
        # Prefer text_html to preserve custom emojis (<tg-emoji>), bold, links, etc.
        orig_text = (
            getattr(original_msg, 'text_html', None)
            or (cache.get(f"msg_html_{msg_id}") if msg_id else None)
            or getattr(original_msg, 'text', '')
            or ''
        )
        if orig_text == "Media/File":
            orig_text = ''

        new_text = f"{orig_text}\n\n{signature_content}".strip() if orig_text else signature_content
        try:
            await context.bot.send_message(chat_id=chat_id, text=new_text, parse_mode='HTML', disable_web_page_preview=True)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=new_text, disable_web_page_preview=True)
    else:
        # Prefer caption_html to preserve custom emojis in photo/video captions
        orig_caption = (
            getattr(original_msg, 'caption_html', None)
            or (cache.get(f"msg_caption_html_{msg_id}") if msg_id else None)
            or getattr(original_msg, 'caption', '')
            or ''
        )
        if orig_caption == "Media/File":
            orig_caption = ''

        new_caption = f"{orig_caption}\n\n{signature_content}".strip() if orig_caption else signature_content
        if len(new_caption) > 1024:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=msg_id)
            try:
                await context.bot.send_message(chat_id=chat_id, text=signature_content, parse_mode='HTML')
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=signature_content)
        else:
            try:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=msg_id, caption=new_caption, parse_mode='HTML')
            except Exception:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=msg_id, caption=new_caption)

# --- INLINE MODE ---

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    if not query: return
    
    user = await get_or_create_user(update.effective_user)
    sigs = [sig async for sig in Signature.objects.filter(user=user)]
    
    results = []
    for sig in sigs:
        results.append(
            InlineQueryResultArticle(
                id=str(sig.id),
                title=f"Sign: {sig.name}",
                description=sig.content[:40],
                input_message_content=InputTextMessageContent(
                    f"{query}\n\n{sig.content}",
                    parse_mode='HTML'
                )
            )
        )
    await update.inline_query.answer(results, cache_time=0)
