import os
import re
import asyncio
import logging
from telegram import (
    Update, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import asyncpg

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── ENV ──────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
CHANNEL_IDS  = [int(x.strip()) for x in os.environ["CHANNEL_IDS"].split(",")]

# ADMIN_IDS: comma-separated; first ID is the owner
_env_admin_ids = [int(x.strip()) for x in os.environ["ADMIN_IDS"].split(",")]
OWNER_ID       = _env_admin_ids[0]

# ── DB POOL + IN-MEMORY CACHE ─────────────────────────────────────────
_pool: asyncpg.Pool = None
_footer_cache: str  = None
_admin_cache: set   = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    return _pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS footer (
                id      SERIAL PRIMARY KEY,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_posts (
                id       SERIAL PRIMARY KEY,
                msg_type TEXT NOT NULL,
                caption  TEXT,
                file_id  TEXT,
                raw_text TEXT
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)
        # Seed env-defined admins into DB (idempotent)
        for aid in _env_admin_ids:
            await conn.execute(
                "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                aid
            )
    logger.info("DB initialized.")

# ── ADMIN HELPERS ─────────────────────────────────────────────────────
async def load_admins() -> set:
    global _admin_cache
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
    _admin_cache = {r["user_id"] for r in rows}
    return _admin_cache

async def get_admins() -> set:
    global _admin_cache
    if _admin_cache is not None:
        return _admin_cache
    return await load_admins()

def is_admin_id(user_id: int, admins: set) -> bool:
    return user_id in admins

def is_owner_id(user_id: int) -> bool:
    return user_id == OWNER_ID

async def add_admin_db(user_id: int):
    global _admin_cache
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )
    if _admin_cache is not None:
        _admin_cache.add(user_id)

async def remove_admin_db(user_id: int):
    global _admin_cache
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
    if _admin_cache is not None:
        _admin_cache.discard(user_id)

# ── HELPERS ───────────────────────────────────────────────────────────
URL_PATTERN = re.compile(
    r'(https?://[^\s]+|t\.me/[^\s]+|www\.[^\s]+)',
    re.IGNORECASE
)

def filter_links(text: str) -> str:
    """
    - Find the LAST 'tera' link in the text.
    - Keep everything above it unchanged (non-tera links removed).
    - Keep the last tera link itself.
    - Remove everything after the last tera link.
    """
    if not text:
        return text or ""

    matches = list(URL_PATTERN.finditer(text))

    last_tera = None
    for m in matches:
        if "tera" in m.group(0).lower():
            last_tera = m

    if last_tera is None:
        result = URL_PATTERN.sub("", text)
        result = re.sub(r'  +', ' ', result).strip()
        return result

    before_and_link = text[:last_tera.end()]

    def keep_tera_only(m):
        return m.group(0) if "tera" in m.group(0).lower() else ""

    result = URL_PATTERN.sub(keep_tera_only, before_and_link)
    result = re.sub(r'  +', ' ', result).strip()
    return result

async def get_footer() -> str:
    global _footer_cache
    if _footer_cache is not None:
        return _footer_cache
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT content FROM footer ORDER BY id DESC LIMIT 1")
    _footer_cache = row["content"] if row else ""
    return _footer_cache

async def get_pending() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM pending_posts ORDER BY id ASC")

async def clear_pending():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM pending_posts")

async def add_pending(msg_type, caption=None, file_id=None, raw_text=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO pending_posts (msg_type, caption, file_id, raw_text) VALUES ($1,$2,$3,$4)",
            msg_type, caption, file_id, raw_text
        )

def build_preview(text: str, footer: str) -> str:
    if footer:
        return f"{text}\n\n{footer}".strip()
    return text.strip()

# ── COMMANDS ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admins = await get_admins()
    if not is_admin_id(update.effective_user.id, admins):
        return
    pending = await get_pending()
    footer  = await get_footer()
    is_owner = is_owner_id(update.effective_user.id)
    await update.message.reply_text(
        f"👋 *Link Filter Bot Active*\n\n"
        f"📦 Pending posts: `{len(pending)}`\n"
        f"📝 Footer: `{'Set ✅' if footer else 'Not set ❌'}`\n"
        f"👤 Role: `{'Owner 👑' if is_owner else 'Admin'}`\n\n"
        f"*How to use:*\n"
        f"1. Posts bhejo (text/photo/video/doc)\n"
        f"2. Preview turant milega\n"
        f"3. /send karo channels mein distribute karne ke liye\n\n"
        f"_Sirf 'tera' wale links rakhta hai, baaki remove hote hain._",
        parse_mode="Markdown"
    )

async def cmd_footer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admins = await get_admins()
    if not is_admin_id(update.effective_user.id, admins):
        return

    msg = update.message
    full_text = msg.text or ""
    if full_text.lower().startswith("/footer"):
        content = full_text[len("/footer"):].strip()
    else:
        content = ""

    if not content:
        current = await get_footer()
        display = f"<b>Current footer:</b>\n{current}" if current else "Footer set nahi hai abhi."
        await msg.reply_text(
            f"{display}\n\n<b>Usage:</b> <code>/footer your text here</code>\n"
            f"Newlines, HTML (bold, italic, hyperlinks) sab support hai.\n\n"
            f"Example:\n<code>/footer 𝙅𝙤𝙞𝙣 𝙈𝙖𝙞𝙣 𝘾𝙝𝙖𝙣𝙣𝙚𝙡\n&lt;a href=\"https://t.me/linkbazr\"&gt;https://t.me/linkbazr&lt;/a&gt;</code>",
            parse_mode="HTML"
        )
        return

    global _footer_cache
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM footer")
        await conn.execute("INSERT INTO footer (content) VALUES ($1)", content)
    _footer_cache = content
    await msg.reply_text(
        f"✅ <b>Footer saved!</b>\n\n{content}",
        parse_mode="HTML"
    )

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admins = await get_admins()
    if not is_admin_id(update.effective_user.id, admins):
        return
    count = len(await get_pending())
    await clear_pending()
    ctx.user_data["collecting"] = False
    await update.message.reply_text(
        f"🗑️ *Batch cancelled.*\n`{count}` posts clear ho gaye.\n\nNaye posts bhejo naya batch shuru karne ke liye.",
        parse_mode="Markdown"
    )

async def cmd_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only: list all current admins."""
    if not is_owner_id(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf owner ye command use kar sakta hai.")
        return
    admins = await get_admins()
    lines = []
    for uid in sorted(admins):
        tag = " 👑 (owner)" if uid == OWNER_ID else ""
        lines.append(f"• <code>{uid}</code>{tag}")
    text = "<b>👥 Current Admins:</b>\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only: /addadmin <user_id>"""
    if not is_owner_id(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf owner admins add kar sakta hai.")
        return
    args = ctx.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: <code>/addadmin &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    new_id = int(args[0])
    admins = await get_admins()
    if new_id in admins:
        await update.message.reply_text(f"ℹ️ <code>{new_id}</code> pehle se admin hai.", parse_mode="HTML")
        return
    await add_admin_db(new_id)
    await update.message.reply_text(
        f"✅ <code>{new_id}</code> ko admin bana diya gaya.", parse_mode="HTML"
    )

async def cmd_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only: /removeadmin <user_id>"""
    if not is_owner_id(update.effective_user.id):
        await update.message.reply_text("⛔ Sirf owner admins remove kar sakta hai.")
        return
    args = ctx.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: <code>/removeadmin &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(args[0])
    if target_id == OWNER_ID:
        await update.message.reply_text("⛔ Owner ko remove nahi kar sakte.")
        return
    admins = await get_admins()
    if target_id not in admins:
        await update.message.reply_text(f"ℹ️ <code>{target_id}</code> admin nahi hai.", parse_mode="HTML")
        return
    await remove_admin_db(target_id)
    await update.message.reply_text(
        f"✅ <code>{target_id}</code> ko admin se remove kar diya gaya.", parse_mode="HTML"
    )

async def send_one(bot, post, channel_id, footer, retries=3):
    """Send a single post with FloodWait retry logic."""
    caption = post["caption"] or ""
    filtered_caption = filter_links(caption)
    final_caption = build_preview(filtered_caption, footer)
    msg_type = post["msg_type"]

    for attempt in range(retries):
        try:
            if msg_type == "text":
                text = filter_links(post["raw_text"] or "")
                final_text = build_preview(text, footer)
                await bot.send_message(chat_id=channel_id, text=final_text, parse_mode="HTML")
            elif msg_type == "photo":
                await bot.send_photo(chat_id=channel_id, photo=post["file_id"], caption=final_caption, parse_mode="HTML")
            elif msg_type == "video":
                await bot.send_video(chat_id=channel_id, video=post["file_id"], caption=final_caption, parse_mode="HTML")
            elif msg_type == "document":
                await bot.send_document(chat_id=channel_id, document=post["file_id"], caption=final_caption, parse_mode="HTML")
            elif msg_type == "audio":
                await bot.send_audio(chat_id=channel_id, audio=post["file_id"], caption=final_caption, parse_mode="HTML")
            return True, None

        except Exception as e:
            err_str = str(e)
            if "flood" in err_str.lower() or "retry" in err_str.lower():
                import re as _re
                wait = 30
                m = _re.search(r"retry after (\d+)", err_str, _re.IGNORECASE)
                if m:
                    wait = int(m.group(1)) + 2
                logger.warning(f"FloodWait {wait}s for channel {channel_id}, attempt {attempt+1}")
                await asyncio.sleep(wait)
                continue
            logger.error(f"Post {post['id']} → {channel_id} FAILED: {err_str}")
            return False, err_str

    return False, "Max retries exceeded"


async def cmd_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admins = await get_admins()
    if not is_admin_id(update.effective_user.id, admins):
        return
    posts = await get_pending()
    if not posts:
        await update.message.reply_text("⚠️ Koi pending post nahi hai. Pehle posts bhejo.")
        return

    footer = await get_footer()
    total  = len(posts)
    sent   = 0
    failed_logs = []

    status_msg = await update.message.reply_text(
        f"📤 <b>Sending {total} posts...</b>", parse_mode="HTML"
    )

    for i, post in enumerate(posts):
        channel_id = CHANNEL_IDS[i % len(CHANNEL_IDS)]
        ok, err = await send_one(ctx.bot, post, channel_id, footer)
        if ok:
            sent += 1
        else:
            failed_logs.append(f"Post #{i+1} → {channel_id}: {err}")
        await asyncio.sleep(0.8)

    await clear_pending()
    ctx.user_data["collecting"] = False

    if sent == total:
        summary = f"✅ <b>Done! {sent}/{total} posts sent successfully.</b>\n📺 Channels: <code>{len(CHANNEL_IDS)}</code>"
    else:
        errors = total - sent
        summary = f"⚠️ <b>{sent}/{total} sent.</b> {errors} failed.\n\n"
        summary += "\n".join(failed_logs[:10])

    await status_msg.edit_text(summary, parse_mode="HTML")

# ── MESSAGE HANDLER ───────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admins = await get_admins()
    if not is_admin_id(update.effective_user.id, admins):
        return
    msg = update.message
    if not msg:
        return

    if not ctx.user_data.get("collecting"):
        await clear_pending()
        ctx.user_data["collecting"] = True
        ctx.user_data["batch_count"] = 0

    footer = await get_footer()

    if msg.text and not msg.text.startswith("/"):
        filtered = filter_links(msg.text)
        await add_pending("text", raw_text=filtered)
        preview = build_preview(filtered, footer)
        await msg.reply_text(
            f"📋 *Preview:*\n\n{preview}",
            parse_mode="Markdown"
        )

    elif msg.photo:
        file_id = msg.photo[-1].file_id
        caption = filter_links(msg.caption or "")
        await add_pending("photo", caption=caption, file_id=file_id)
        preview_caption = build_preview(caption, footer)
        await msg.reply_photo(
            photo=file_id,
            caption=f"📋 Preview:\n\n{preview_caption}"
        )

    elif msg.video:
        file_id = msg.video.file_id
        caption = filter_links(msg.caption or "")
        await add_pending("video", caption=caption, file_id=file_id)
        preview_caption = build_preview(caption, footer)
        await msg.reply_video(
            video=file_id,
            caption=f"📋 Preview:\n\n{preview_caption}"
        )

    elif msg.document:
        file_id = msg.document.file_id
        caption = filter_links(msg.caption or "")
        await add_pending("document", caption=caption, file_id=file_id)
        preview_caption = build_preview(caption, footer)
        await msg.reply_document(
            document=file_id,
            caption=f"📋 Preview:\n\n{preview_caption}"
        )

    elif msg.audio:
        file_id = msg.audio.file_id
        caption = filter_links(msg.caption or "")
        await add_pending("audio", caption=caption, file_id=file_id)
        preview_caption = build_preview(caption, footer)
        await msg.reply_audio(
            audio=file_id,
            caption=f"📋 Preview:\n\n{preview_caption}"
        )

    else:
        await msg.reply_text("⚠️ Unsupported media type.")
        return

    ctx.user_data["batch_count"] = ctx.user_data.get("batch_count", 0) + 1

# ── SETUP & MAIN ──────────────────────────────────────────────────────
async def post_init(app: Application):
    await init_db()
    await load_admins()   # warm the cache
    await app.bot.set_my_commands([
        BotCommand("start",       "Bot status dekhein"),
        BotCommand("footer",      "Footer set ya dekhein"),
        BotCommand("send",        "Saare posts channels mein bhejein"),
        BotCommand("cancel",      "Current batch cancel karein"),
        BotCommand("admins",      "Admins list dekhein (owner only)"),
        BotCommand("addadmin",    "Admin add karein (owner only)"),
        BotCommand("removeadmin", "Admin remove karein (owner only)"),
    ])
    logger.info("Commands registered.")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("footer",      cmd_footer))
    app.add_handler(CommandHandler("send",        cmd_send))
    app.add_handler(CommandHandler("cancel",      cmd_cancel))
    app.add_handler(CommandHandler("admins",      cmd_admins))
    app.add_handler(CommandHandler("addadmin",    cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message
    ))

    logger.info("Bot polling started...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
