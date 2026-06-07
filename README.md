# 🤖 Link Filter Bot — Tera Edition

A Telegram bot for admins to **filter, preview, and batch-send posts** to multiple channels — keeping only `tera` links (e.g. Terabox) and removing all other URLs automatically.

---

## ✨ Features

- 🔗 **Auto Link Filter** — keeps only URLs containing `tera`, removes everything else
- 📋 **Instant Preview** — shows filtered preview before sending
- 📦 **Batch Posting** — collect multiple posts then send all at once
- 📺 **Multi-Channel Support** — distributes posts across multiple channels (round-robin)
- 📝 **Custom Footer** — set a persistent footer appended to every post
- 🔁 **FloodWait Retry** — auto-retries on Telegram rate limits
- 👥 **Multi-Admin Support** — multiple admins, one owner with full control

---

## 🗂️ Project Structure

```
.
├── main.py          # Bot source code
├── requirements.txt # Python dependencies
├── Procfile         # For deployment (Railway/Render)
└── .env             # Environment variables (not committed)
```

---

## ⚙️ Environment Variables

| Variable       | Description                                                      | Example                                        |
|----------------|------------------------------------------------------------------|------------------------------------------------|
| `BOT_TOKEN`    | Your bot token from [@BotFather](https://t.me/BotFather)        | `123456:ABC-DEF...`                            |
| `ADMIN_IDS`    | Comma-separated admin user IDs — **first ID is the owner**       | `987654321,111222333,444555666`                 |
| `DATABASE_URL` | PostgreSQL connection string                                     | `postgresql://user:pass@host/db?sslmode=require` |
| `CHANNEL_IDS`  | Comma-separated target channel IDs                               | `-1001234567890,-1009876543210`                 |

> **Note:** The first ID in `ADMIN_IDS` becomes the **owner** — only the owner can add/remove other admins.

---

## 🚀 Setup & Deployment

### Local / VPS

```bash
# 1. Clone the repo
git clone https://github.com/YOUR/REPO.git
cd REPO

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create env file
nano .bot.env   # fill in all variables

# 4. Run
python main.py
```

### Systemd Service (Google Cloud / Linux VPS)

```ini
# /etc/systemd/system/telegrambot.service
[Unit]
Description=Telegram Link Filter Bot (Tera)
After=network.target

[Service]
User=your_user
WorkingDirectory=/home/your_user/REPO
EnvironmentFile=/home/your_user/REPO/.bot.env
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegrambot
sudo systemctl start telegrambot
```

### Railway Deployment

1. Push code to GitHub
2. railway.app → New Project → Deploy from GitHub repo
3. Add environment variables in the Variables tab
4. Railway auto-deploys on every push

---

## 📖 Commands

### All Admins

| Command   | Description                                  |
|-----------|----------------------------------------------|
| `/start`  | Show bot status, pending count, footer, role |
| `/footer` | View or set footer text (HTML supported)     |
| `/send`   | Send all pending posts to channels           |
| `/cancel` | Clear current batch without sending          |

### Owner Only

| Command                  | Description                     |
|--------------------------|---------------------------------|
| `/admins`                | List all current admins         |
| `/addadmin <user_id>`    | Add a new admin                 |
| `/removeadmin <user_id>` | Remove an existing admin        |

---

## 📤 How to Use

1. **Send posts** to the bot (text, photo, video, document, audio)
2. Bot filters all non-`tera` links and shows a **preview**
3. Send more posts to build a batch
4. Run `/send` — bot distributes posts across all configured channels
5. Use `/cancel` to discard the batch and start fresh

---

## 🔗 Link Filtering Logic

```
Input:  "Check this out https://drive.google.com/xyz and https://terabox.com/abc"
Output: "Check this out https://terabox.com/abc"
```

- Last `tera` URL is kept; everything after it is removed
- All non-`tera` URLs before it are also removed
- If no `tera` URL found → all links are removed

### Examples

| URL | Result |
|-----|--------|
| `https://terabox.com/xyz` | ✅ Kept |
| `https://myteralink.com/abc` | ✅ Kept |
| `https://drive.google.com/xyz` | ❌ Removed |
| `https://t.me/someChannel` | ❌ Removed |

---

## 👥 Admin System

- **Owner** = first ID in `ADMIN_IDS` env var (permanent, cannot be removed)
- **Admins** = stored in DB, persist across restarts
- All env-defined IDs are auto-seeded into DB on startup
- Owner manages admins at runtime via `/addadmin` and `/removeadmin`

---

## 🗄️ Database Schema

```sql
CREATE TABLE footer (
    id      SERIAL PRIMARY KEY,
    content TEXT NOT NULL
);

CREATE TABLE pending_posts (
    id       SERIAL PRIMARY KEY,
    msg_type TEXT NOT NULL,   -- text | photo | video | document | audio
    caption  TEXT,
    file_id  TEXT,
    raw_text TEXT
);

CREATE TABLE admins (
    user_id BIGINT PRIMARY KEY
);
```

---

## 📦 Dependencies

| Package               | Version | Purpose                  |
|-----------------------|---------|--------------------------|
| `python-telegram-bot` | 21.10   | Telegram Bot API wrapper |
| `asyncpg`             | 0.30.0  | Async PostgreSQL client  |

---

## 📄 License

MIT — free to use and modify.
