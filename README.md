# Telegram Community Broadcast Bot

Telegram broadcast bot with manual approval, VIP/Admin roles, duplicate content detection, auth group validation, and multi-instance shared registry.

## Features

- **Broadcast system** — forwards media and messages to all approved users with reply threading
- **Manual approval** — optional mode requiring admin approval for new users
- **VIP / Admin roles** — special permissions and dynamic command menus per user
- **Anti-duplicate** — blocks duplicate media within a configurable window
- **Inactivity handling** — warnings and auto-removal after configurable hours
- **Report by reply** — users report inappropriate content; admins are notified with action buttons
- **Auth group** — restrict bot access to members of a specific Telegram group or channel
- **Capacity limit** — set a maximum number of regular users allowed in the bot
- **Broadcast forward channel** — mirror all broadcasts to a secondary channel
- **Customizable /start and /rules** — set photo + text via admin commands, no code changes needed
- **Fix / Unfix** — pin or unpin a message across all member chats simultaneously
- **Erase** — delete a broadcast message from all member chats
- **Scan** — list users inactive for 3+ days with bulk-ban option
- **Multi-instance shared registry** — run multiple bot instances that refuse to share users between them

## Requirements

- Python 3.11+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- API credentials from [my.telegram.org](https://my.telegram.org)

## Project structure

```
├── main.py              # Bot entry point and handlers
├── config.py            # Configuration (env vars)
├── database.py          # SQLite operations
├── utils.py             # Rate limit, helpers
├── shared_registry.py   # Multi-instance user registry
├── clean.py             # Database cleanup utility
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example         # Copy to .env and fill in your values
└── README.md
```

## Installation

### Option A — Docker (recommended)

```bash
git clone https://github.com/your-user/bot_chatES.git
cd bot_chatES
cp .env.example .env
# Edit .env with your API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
docker compose up -d
docker compose logs -f
```

### Option B — Local Python

```bash
git clone https://github.com/your-user/bot_chatES.git
cd bot_chatES
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env
python main.py
```

## Configuration

Copy `.env.example` to `.env` and fill in your values. Key variables:

| Variable | Default | Description |
|---|---|---|
| `API_ID` | — | From my.telegram.org |
| `API_HASH` | — | From my.telegram.org |
| `BOT_TOKEN` | — | From @BotFather |
| `ADMIN_IDS` | — | Comma-separated admin user IDs |
| `PROTECT_CONTENT` | `true` | Disable message forwarding by default |
| `BLOCK_DUPLICATES` | `false` | Block duplicate media |
| `DUPLICATE_WINDOW_HOURS` | `72` | Hours window for duplicate check |
| `INACTIVITY_HOURS` | `72` | Hours before inactive user is removed |
| `MAX_CONCURRENT` | `50` | Parallel sends per broadcast |
| `SEND_DELAY` | `0.05` | Seconds between each send |
| `RATE_LIMIT` | `30` | Messages per user per window |
| `RATE_WINDOW` | `20` | Rate limit window in seconds |
| `SYNC_CHANNEL_ID` | `0` | Mirror broadcasts to channel (0 = off) |
| `WELCOME_RULES` | — | Default welcome text (overridden by /setstart) |
| `BOT_INSTANCE_ID` | `bot1` | Unique ID for multi-instance registry |
| `SHARED_REGISTRY_PATH` | `shared/registry.db` | Shared registry DB path |

## Commands

### User commands

| Command | Description |
|---|---|
| `/start` | Register and receive welcome message |
| `/rules` | View group rules |
| `/me` | View your status (approval, VIP, points) |
| `/report` | Report a user (reply to their message) |
| `/renv` | Re-send a media/album to yourself (VIP/Admin) |

### Admin commands — Content

| Command | Description |
|---|---|
| `/setrules` | Set photo and/or text for `/rules` (reply to a photo or text) |
| `/setstart` | Set photo and/or text for `/start` (reply to a photo or text) |
| `/fix` | Send and pin a message across all member chats |
| `/unfix` | Unpin messages from all member chats |
| `/erase` | Delete a broadcast message from all member chats (reply to it) |

### Admin commands — Users

| Command | Description |
|---|---|
| `/stats` | Full bot statistics |
| `/list_users` | List all approved users (paginated) |
| `/showuser <id>` | Detailed info for a specific user |
| `/whois <name/@user>` | Search users by name or username |
| `/addadmin <id/@user>` | Promote user to admin |
| `/removeadmin <id/@user>` | Remove admin privileges |
| `/vip <id/@user>` | Grant permanent VIP status |
| `/unvip <id/@user>` | Remove VIP status |
| `/ban <id/@user> [reason]` | Permanently ban a user |
| `/unban <id/@user>` | Remove ban |
| `/listban` | List banned users (paginated) |
| `/scan` | List users inactive 3+ days with bulk-ban option |

### Admin commands — Approval

| Command | Description |
|---|---|
| `/approve` | Toggle manual approval mode on/off |
| `/listap` / `/pending` | List users waiting for approval |
| `/a` | Approve a pending user (reply to their request) |
| `/d` | Reject a pending user (reply to their request) |

### Admin commands — Settings

| Command | Description |
|---|---|
| `/toggleforward` | Toggle content forwarding protection |
| `/setauthgroup` | Restrict bot to members of a group/channel (use in that group) |
| `/delauthgroup` | Remove the auth group restriction |
| `/setforward` | Set a channel to mirror all broadcasts (use in that channel) |
| `/delforward` | Remove the forward channel |
| `/setcapacity <n>` | Set maximum number of regular users (0 = unlimited) |
| `/dupes_stats` | Users with most blocked duplicates |

## Multi-instance shared registry

Run multiple bots from the same codebase and prevent a user registered in one from joining the others.

1. Each instance needs a unique `BOT_INSTANCE_ID` in its `.env`.
2. All instances must mount the same `shared/` volume.
3. In `docker-compose.yml`, add `./shared:/app/shared` to each service's volumes.

## Performance

- **UVLOOP** — high-performance asyncio event loop (2–4× faster, auto-detected)
- **PyroFork + tgcrypto** — optimized MTProto client with accelerated encryption
- **Concurrent broadcasts** — `MAX_CONCURRENT=50` parallel sends; 1 000 users ≈ 20–25 s
- **SQLite WAL** — low-latency database with write-ahead logging

## Database cleanup

Remove corrupted or invalid entries from the database:

```bash
python clean.py
```

## Dependencies

| Package | Purpose |
|---|---|
| pyrofork | Telegram MTProto client (Pyrogram fork) |
| tgcrypto | Fast crypto for Telegram |
| python-dotenv | Load `.env` variables |
| uvloop | High-performance asyncio (optional) |

## License

MIT
