# ytnd/bot.py
"""
Telegram bot for YTND with Syncthing integration and QR code support.
"""
from __future__ import annotations
import asyncio, tempfile, textwrap, io, qrcode
from pathlib import Path
from typing import Dict
import re

from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackContext, filters,
)

import secrets, time, urllib.parse, os
from .manager_tokens import issue_token
from .config import BOT_TOKEN, DEFAULT_ADMIN_ID, OUTPUT_ROOT, COOKIES_FILE
from .utils import logger, sanitize_filename
from .downloader import Downloader
from .syncthing_client import SyncthingClient
from . import database

try:
    syncthing = SyncthingClient()
except Exception as e:
    logger.error("Failed to initialize Syncthing client: %s", e)
    syncthing = None
def require_auth(role: str = "user"):
    def deco(func):
        async def wrapper(update: Update, context: CallbackContext, *a, **kw):
            uid = str(update.effective_user.id)
            user = database.get_user(uid)
            if not user:
                await update.message.reply_text("❌ You are not authorized.")
                return
            if role == "admin" and user["role"] != "admin":
                await update.message.reply_text("❌ No admin privileges.")
                return
            return await func(update, context, *a, **kw)
        return wrapper
    return deco

async def _send_server_id_qr(update: Update, caption_prefix: str = ""):
    """Send server device ID and QR code to the user."""
    if not syncthing:
        await update.message.reply_text("❌ Syncthing client not available.")
        return
    
    try:
        server_id = syncthing.my_id
    except Exception as e:
        logger.error("Failed to get Syncthing device ID: %s", e)
        await update.message.reply_text("❌ Error retrieving Syncthing device ID.")
        return
    
    buf = io.BytesIO()
    qrcode.make(server_id).save(buf, format="PNG")
    buf.seek(0)
    await update.message.reply_photo(
        photo=buf,
        caption=textwrap.dedent(f"""
            {caption_prefix}
            *Server Device ID*  
            `{server_id}`

            Scan the QR code in your Syncthing app
            (Devices → + Device → QR Code) to add the server.
        """).strip(),
        parse_mode="Markdown")
    buf.close()

@require_auth()
async def start(update: Update, context: CallbackContext):
    uid = str(update.effective_user.id)
    user = database.get_user(uid)
    role = user["role"] if user else "user"
    msg = textwrap.dedent("""
        🎵 *YTND-Bot* – YouTube Audio Downloader

        Send YouTube links or a `.txt` file to add them to your queue.

        Commands:
        • /download   – Process queue
        • /status     – Show status
        • /clear      – Clear queue
        • /sync       – Syncthing pairing / Status / Resync / QR code
        • /manager    – One-time link to web manager
    """)
    if role == "admin":
        msg += textwrap.dedent("""

            *Admin:*
            • /adduser `<ID> <role>`  – Create user
            • /removeuser `<ID>`      – Delete user
            • /listusers              – List users
            • /cookies                – Manage cookies
        """)
    await update.message.reply_text(msg.strip(), parse_mode="Markdown")

@require_auth()
async def add_url(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()


    url_re = re.compile(
        r'(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s<>\)]+)',
        re.IGNORECASE
    )
    urls = [u.strip('.,);]') for u in url_re.findall(text)]

    if not urls:
        await update.message.reply_text("❌ No YouTube link detected.")
        return

    Downloader(update.effective_user.id).add_urls(urls)
    if len(urls) == 1:
        await update.message.reply_text("✅ Link saved.")
    else:
        await update.message.reply_text(f"✅ {len(urls)} links saved.")


@require_auth()
async def import_txt(update: Update, context: CallbackContext):
    await update.message.reply_text("📤 Upload a `.txt` file.")
    context.user_data["await_file"] = True
    context.user_data.pop("await_cookies", None)


@require_auth()
async def handle_document(update: Update, context: CallbackContext):
    if context.user_data.get("await_cookies", False):
        return

    if not context.user_data.pop("await_file", False):
        return

    doc: Document = update.message.document
    if not (doc.file_name and doc.file_name.lower().endswith(".txt")):
        await update.message.reply_text("❌ Only `.txt` files are accepted.")
        return
    
    if doc.file_size and doc.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("❌ File too large. Maximum size: 5 MB.")
        return

    safe_filename = sanitize_filename(doc.file_name)
    tmp = Path(tempfile.gettempdir()) / safe_filename
    
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(tmp))

        text = tmp.read_text(encoding="utf-8", errors="ignore")
        url_re = re.compile(
            r'(https?://(?:www\.)?(?:youtube\.com|youtu\.be)[^\s<>\)]+)',
            re.IGNORECASE
        )
        urls = [u.strip('.,);]') for u in url_re.findall(text)]

        if not urls:
            await update.message.reply_text("ℹ️ No valid YouTube links found in the file.")
        else:
            Downloader(update.effective_user.id).add_urls(urls)
            await update.message.reply_text(f"✅ {len(urls)} links imported.")
    except Exception as e:
        logger.error("Error processing uploaded file: %s", e)
        await update.message.reply_text(f"❌ Error processing file: {e}")
    finally:
        tmp.unlink(missing_ok=True)

@require_auth()
async def clear_queue(update: Update, _):
    uid = str(update.effective_user.id)
    try:
        database.set_queue(uid, [])
        await update.message.reply_text("🗑️ Queue cleared.")
    except Exception as e:
        logger.error("Failed to clear queue for user %s: %s", uid, e)
        await update.message.reply_text(f"❌ Error clearing queue: {e}")

@require_auth()
async def status(update: Update, _):
    await update.message.reply_text("ℹ️ For detailed progress numbers, use /download while running.")

@require_auth()
async def download(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    d   = Downloader(uid)
    loop = asyncio.get_running_loop()

    await update.message.reply_text("🚀 Download running …")

    try:
        stats = await loop.run_in_executor(None, d.run)
        downloaded = stats.get("downloaded", 0)
        dup        = stats.get("duplicates", 0)
        errs       = stats.get("errors", 0)
        failed     = stats.get("failed", []) or []

        lines = []
        if downloaded > 0:
            lines.append(f"✅ Newly downloaded: {downloaded}")
        if dup > 0:
            lines.append(f"↩️ Skipped (duplicates): {dup}")
        if errs > 0:
            lines.append(f"❌ Errors: {errs}")

            preview = failed[:5]
            for f in preview:
                t = f.get("title") or "—"
                a = f.get("artist") or "—"
                r = f.get("reason") or "Error"
                lines.append(f"• {t} – {a}\n  ↳ {r}")

            if len(failed) > 5:
                lines.append(f"… and {len(failed)-5} more errors")

        if not lines:
            lines = ["ℹ️ Nothing to do."]

        any_403 = any("403" in (f.get("reason","")) or "429" in (f.get("reason","")) for f in failed)
        if any_403:
            lines.append("🔐 Note: 403/429 → often login via cookies helps.\nAdmin can upload cookies.txt with /cookies upload.")

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        await update.message.reply_text(f"❌ Unexpected error: {e}")

@require_auth()
async def sync_cmd(update: Update, context: CallbackContext):
    uid  = str(update.effective_user.id)
    user = database.get_user(uid)
    if not user:
        await update.message.reply_text("❌ User not found.")
        return
    args = context.args

    if not args:
        await update.message.reply_text(textwrap.dedent("""
            🔄 Syncthing Commands

            /sync set <YOUR_ID> – Pair device
            /sync qr             – Server ID as QR code
            /sync status         – Show sync status
            /sync rescan         – Rescan folder

            Find your device ID in Syncthing: Devices → Own Device → ID.
            Syncthing App: https://syncthing.net/downloads/
        """).strip())
        return

    if args[0] in ("qr", "server"):
        await _send_server_id_qr(update)
        return

    if args[0] == "set":
        if not syncthing:
            await update.message.reply_text("❌ Syncthing client not available.")
            return
        
        if len(args) != 2:
            await update.message.reply_text("Usage: /sync set <Device-ID>")
            return
        dev_id = args[1].strip().upper()
        
        if len(dev_id) < 50 or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567-" for c in dev_id):
            await update.message.reply_text("❌ Invalid device ID. Please check the ID.")
            return
        
        database.update_user_syncthing_id(uid, dev_id)

        try:
            folder_path = OUTPUT_ROOT / uid
            folder_path.mkdir(exist_ok=True, parents=True)
            
            stignore_path = folder_path / ".stignore"
            if not stignore_path.exists():
                stignore_content = textwrap.dedent("""
                    // Syncthing Ignore Patterns
                    //
                    // See https://docs.syncthing.net/users/ignoring.html
                    
                    // Android/system files
                    .nomedia
                    .thumbnails
                    
                    // Temporary or incomplete downloads
                    // (Handled by yt-dlp, but good to have as a fallback)
                    *.part
                    *.ytdl
                    
                    // Other common metadata files
                    Thumbs.db
                    desktop.ini
                """).strip()
                stignore_path.write_text(stignore_content, encoding="utf-8")

            syncthing.ensure_device(dev_id, name=f"user_{uid}")
            folder_id   = f"ytnd_{uid}"
            syncthing.ensure_folder(folder_id, folder_path, dev_id)
            syncthing.rescan(folder_id)
        except Exception as e:
            logger.error("Syncthing setup failed for user %s: %s", uid, e)
            await update.message.reply_text(f"❌ Error setting up Syncthing: {e}")
            return

        await update.message.reply_text(textwrap.dedent(f"""
            ✅ Successfully paired!

            Folder ID : {folder_id}

            Open Syncthing on your device and accept the share.
            If no request appears, scan the QR code with /sync qr.
        """).strip())
        await _send_server_id_qr(update)
        return

    if args[0] == "rescan":
        if not syncthing:
            await update.message.reply_text("❌ Syncthing client not available.")
            return
        
        if not user.get("syncthing_device"):
            await update.message.reply_text("You haven't paired a device yet. → /sync set <ID>")
            return
        folder_id = f"ytnd_{uid}"
        try:
            syncthing.rescan(folder_id)
            await update.message.reply_text("🔄 Rescan triggered.")
        except Exception as e:
            logger.error("Syncthing rescan failed for user %s: %s", uid, e)
            await update.message.reply_text(f"❌ Rescan error: {e}")
        return

    if args[0] == "status":
        if not syncthing:
            await update.message.reply_text("❌ Syncthing client not available.")
            return
        
        if not user.get("syncthing_device"):
            await update.message.reply_text("You haven't paired a device yet. → /sync set <ID>")
            return
        folder_id = f"ytnd_{uid}"
        try:
            st = syncthing.folder_status(folder_id)
            await update.message.reply_text(textwrap.dedent(f"""
                📡 *Syncthing Status*

                Folder ID  : `{folder_id}`
                State      : {st.get('state')}
                Global/Loc.: {st.get('globalBytes',0)//1024**2} MiB /
                            {st.get('localBytes',0)//1024**2} MiB
                Missing   : {st.get('needFiles')}
            """).strip(), parse_mode="Markdown")
        except Exception as e:
            logger.error("Syncthing status check failed for user %s: %s", uid, e)
            await update.message.reply_text(f"❌ Error retrieving status: {e}")
        return

    await update.message.reply_text("Unknown subcommand. Send /sync for help.")


@require_auth()
async def manager_link(update: Update, context: CallbackContext):
    base_url = os.getenv("MANAGER_BASE_URL", "http://127.0.0.1:8080")
    uid = str(update.effective_user.id)
    token = issue_token(uid=uid, ttl_seconds=1800)
    url = f"{base_url}/auth/start?token={urllib.parse.quote(token)}"

    msg = textwrap.dedent(f"""
        YTND Manager

        One-time link (valid for 30 min):
        {url}

        Tip: Open the link in a browser on the device paired with Syncthing.
        If problems occur: first visit /auth/logout in the browser, then open the link again.
    """).strip()

    await update.message.reply_text(msg, disable_web_page_preview=True)

@require_auth("admin")
async def add_user(update: Update, context: CallbackContext):
    if len(context.args) != 2 or context.args[1] not in ("admin", "user"):
        await update.message.reply_text("Usage: /adduser <ID> <admin|user>")
        return
    uid, role = context.args
    try:
        database.add_user(uid, role)
        await update.message.reply_text(f"✅ User {uid} = {role}")
    except ValueError:
        await update.message.reply_text(f"❌ User {uid} already exists.")

@require_auth("admin")
async def remove_user(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /removeuser <ID>")
        return
    uid = context.args[0]
    if uid == DEFAULT_ADMIN_ID:
        await update.message.reply_text("❌ Default admin cannot be removed.")
        return
    if database.remove_user(uid):
        await update.message.reply_text("✅ User removed.")
    else:
        await update.message.reply_text("❌ User not found.")

@require_auth("admin")
async def list_users(update: Update, _):
    users = database.list_users()
    lines = [f"{u} – {d['role']}" for u, d in users.items()]
    await update.message.reply_text("\n".join(lines) or "No users.")

@require_auth("admin")
async def cookies_cmd(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("/cookies upload   – Upload file\n"
                                        "/cookies clear    – Delete file\n"
                                        f"Current: {'present' if COOKIES_FILE.exists() else 'no cookies'}")
        return

    sub = context.args[0].lower()

    if sub == "upload":
        await update.message.reply_text("Please send *cookies.txt* as a file now.")
        context.user_data["await_cookies"] = True
        context.user_data.pop("await_file", None)
        return

    if sub == "clear":
        COOKIES_FILE.unlink(missing_ok=True)
        await update.message.reply_text("Cookies deleted.")
        return

    await update.message.reply_text("Unknown subcommand. /cookies for help.")

@require_auth("admin")
async def handle_cookie_file(update: Update, context: CallbackContext):
    if not context.user_data.pop("await_cookies", False):
        return

    doc: Document = update.message.document
    
    if doc.file_size and doc.file_size > 1024 * 1024:
        await update.message.reply_text("❌ Cookies file too large. Maximum size: 1 MB.")
        return
    
    if doc.mime_type not in ("text/plain", "application/octet-stream"):
        await update.message.reply_text("Please upload a *cookies.txt* file.")
        return

    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(COOKIES_FILE))

        context.user_data.pop("await_file", None)

        await update.message.reply_text("✅ Cookies saved. Future downloads will run with login (if needed).")
    except Exception as e:
        logger.error("Error saving cookies file: %s", e)
        await update.message.reply_text(f"❌ Error saving cookies: {e}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Standard
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.add_handler(CommandHandler("clear", clear_queue))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("import", import_txt))
    app.add_handler(CommandHandler("sync", sync_cmd))
    app.add_handler(CommandHandler("manager", manager_link))

    # Admin
    app.add_handler(CommandHandler("adduser", add_user))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(CommandHandler("listusers", list_users))
    app.add_handler(CommandHandler("cookies", cookies_cmd))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_cookie_file))
    app.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), handle_document, block=False))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_url))

    logger.info("Bot running …")
    app.run_polling()


if __name__ == "__main__":
    main()
