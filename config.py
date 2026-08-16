"""
Bot configuration - Version with manual approval support
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ====================================================================
# TELEGRAM CREDENTIALS
# ====================================================================
_api_id = os.getenv("API_ID")
_api_hash = os.getenv("API_HASH")
_bot_token = os.getenv("BOT_TOKEN")
if not _api_id or not _api_hash or not _bot_token:
    print("❌ Configure API_ID, API_HASH and BOT_TOKEN in the .env file")
    sys.exit(1)
API_ID = int(_api_id)
API_HASH = _api_hash
BOT_TOKEN = _bot_token

# ====================================================================
# ADMIN CONFIGURATION
# ====================================================================
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]

# ====================================================================
# SYNC CHANNEL (OPTIONAL)
# ====================================================================
SYNC_CHANNEL_ID = int(os.getenv("SYNC_CHANNEL_ID", "0"))

# ====================================================================
# PERFORMANCE SETTINGS
# ====================================================================
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "25"))
SEND_DELAY = float(os.getenv("SEND_DELAY", "0.05"))
MEDIA_GROUP_TIMEOUT = float(os.getenv("MEDIA_GROUP_TIMEOUT", "1.0"))

# ====================================================================
# RATE LIMITING
# ====================================================================
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "10"))
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))

# ====================================================================
# ANTI-DUPLICATE SYSTEM (72H WINDOW)
# ====================================================================
BLOCK_DUPLICATES = os.getenv("BLOCK_DUPLICATES", "True").lower() == "true"
DUPLICATE_WINDOW_HOURS = int(os.getenv("DUPLICATE_WINDOW_HOURS", "72"))
DUPLICATE_EXEMPT_ADMINS = os.getenv("DUPLICATE_EXEMPT_ADMINS", "False").lower() == "true"

# ====================================================================
# INACTIVITY (24 HOURS - members removed from broadcast after 24h)
# ====================================================================
INACTIVITY_HOURS = int(os.getenv("INACTIVITY_HOURS", "24"))
INACTIVITY_CHECK_INTERVAL = int(os.getenv("INACTIVITY_CHECK_INTERVAL", "3600"))

# ====================================================================
# SCAN INACTIVE USERS (/scan - days without photo/video to list)
# ====================================================================
SCAN_INACTIVE_DAYS = int(os.getenv("SCAN_INACTIVE_DAYS", "3"))

# ====================================================================
# MAINTENANCE
# ====================================================================
RAM_CLEANUP_INTERVAL = int(os.getenv("RAM_CLEANUP_INTERVAL", "300"))
BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "86400"))
REBOOT_INTERVAL = int(os.getenv("REBOOT_INTERVAL", "21600"))

# ====================================================================
# FILES
# ====================================================================
DB_FILE = os.getenv("DB_FILE", "data/bot.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "data/backups")

# ====================================================================
# MANUAL APPROVAL SYSTEM
# ====================================================================
MANUAL_APPROVAL_MODE = False  # Initially disabled, use /approve to toggle (actual value loaded from database)

# ====================================================================
# RESTRICT FORWARDING (protect content - disable forwarding)
# Default from .env; can be toggled via /toggleforward (persisted in DB)
# ====================================================================
PROTECT_CONTENT_DEFAULT = os.getenv("PROTECT_CONTENT", "true").lower() == "true"

# ====================================================================
# LEGACY (kept for database schema / imports - points system removed)
# ====================================================================
TAG_NAME = os.getenv("TAG_NAME", "TAG")
TAG_THRESHOLD = 100
POINTS_MAX = 110
MEDIA_POINTS = 1

# ====================================================================
# WELCOME/START PHOTO (optional - rules with photo + caption)
# ====================================================================
# WELCOME_PHOTO_FILE_ID: Telegram file_id of a photo (get by forwarding to @getidsbot)
# WELCOME_PHOTO_PATH: Or path to image file (e.g. rules.png). FILE_ID takes priority.
WELCOME_PHOTO_FILE_ID = os.getenv("WELCOME_PHOTO_FILE_ID", "").strip()
WELCOME_PHOTO_PATH = os.getenv("WELCOME_PHOTO_PATH", "").strip()

# ====================================================================
# BOT FOOTER MESSAGE
# ====================================================================
BOT_FOOTER = os.getenv("BOT_FOOTER", "").replace("\\n", "\n")

# ====================================================================
# SHARED REGISTRY (multi-instance exclusivity)
# ====================================================================
BOT_INSTANCE_ID = os.getenv("BOT_INSTANCE_ID", "default")
SHARED_REGISTRY_PATH = os.getenv("SHARED_REGISTRY_PATH", "shared/registry.db")

# ====================================================================
# MESSAGES - Fallback cuando aún no se configuró con /setrules o /setstart
# ====================================================================
WELCOME_RULES = os.getenv("WELCOME_RULES", """
🎬 **¡Bienvenido!**

📋 **Configuración (solo admins):**

• **/setrules** - Definir foto y texto de /rules
  Responde a una foto para la imagen, o a un mensaje de texto para el contenido.

• **/setstart** - Definir foto y texto de /start
  Responde a una foto para la imagen, o a un mensaje de texto para el contenido.

⏳ Límites: 1024 caracteres con foto, 4096 sin foto.
⏳ Usa /me para ver tu estado.
⏳ Usa /report (responder al mensaje) para reportar contenido inapropiado.

""").replace("\\n", "\n")

print("✅ Config loaded")
print(f"📊 Admins: {len(ADMIN_IDS)}")
print(f"⏰ Inactivity: {INACTIVITY_HOURS}h")
print(f"🔄 Rate Limit: {RATE_LIMIT} msgs/{RATE_WINDOW}s")
print(f"🚫 Block Duplicates: {BLOCK_DUPLICATES} (SILENT - {DUPLICATE_WINDOW_HOURS}h)")
print(f"👑 Admin Exemption: {DUPLICATE_EXEMPT_ADMINS}")
print(f"🔐 Manual Approval: {MANUAL_APPROVAL_MODE} (initial value; actual value loaded from DB)")
print(f"🔒 Protect Content (default): {PROTECT_CONTENT_DEFAULT} (toggle via /toggleforward)")
print(f"📷 Welcome photo: {'FILE_ID' if WELCOME_PHOTO_FILE_ID else 'PATH' if WELCOME_PHOTO_PATH else 'None'}")
print(f"📅 Scan inactivos: {SCAN_INACTIVE_DAYS} días")

