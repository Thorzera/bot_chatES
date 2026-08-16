# SQLite database management - V2.8 with clickable reply support
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from config import (
    DB_FILE, ADMIN_IDS, INACTIVITY_HOURS, SCAN_INACTIVE_DAYS,
    PROTECT_CONTENT_DEFAULT, TAG_THRESHOLD, POINTS_MAX, MEDIA_POINTS
)

logger = logging.getLogger(__name__)

def setup_database():
    """Setup database with corrected tables for reply support"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000")
    
    # USERS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            ban_reason TEXT,
            approved INTEGER DEFAULT 1,
            inactivity_warnings INTEGER DEFAULT 0,
            duplicates_blocked INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_72h_notified TIMESTAMP
        )
    """)
    
    # Add last_72h_notified column if not exists
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_72h_notified TIMESTAMP")
        logger.info("Column 'last_72h_notified' added")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # MEDIA HISTORY
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            media_type TEXT,
            file_id TEXT,
            file_unique_id TEXT,
            caption TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    # MESSAGE MAPPING
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_mapping (
            broadcast_message_id INTEGER,
            target_user_id INTEGER,
            original_sender_id INTEGER,
            original_message_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (broadcast_message_id, target_user_id)
        )
    """)
    
    # PENDING APPROVALS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_approvals (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # INDICES
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_active ON users(last_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_approved ON users(approved)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_banned ON users(is_banned)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_type ON media_history(media_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_timestamp ON media_history(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_file_unique ON media_history(file_unique_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_user_unique ON media_history(user_id, file_unique_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_broadcast ON message_mapping(broadcast_message_id, target_user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_original ON message_mapping(original_sender_id, original_message_id)")
    
    # BOT SETTINGS (persistence of options like approval mode)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('manual_approval_mode', 'false')")
    cursor.execute(
        "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('protect_content', ?)",
        ("true" if PROTECT_CONTENT_DEFAULT else "false",)
    )
    
    for col, typ in [("points", "INTEGER DEFAULT 0"), ("has_tag", "INTEGER DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            logger.info(f"Column '{col}' added")
        except sqlite3.OperationalError:
            pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            broadcast_message_id INTEGER,
            target_user_id INTEGER,
            reactor_user_id INTEGER,
            reaction_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (broadcast_message_id, target_user_id, reactor_user_id)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database setup complete")

def get_manual_approval_mode() -> bool:
    """Returns whether manual approval mode is active (persisted in database)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'manual_approval_mode'")
    result = cursor.fetchone()
    conn.close()
    return result is not None and (result[0] or "").lower() == "true"

def set_manual_approval_mode(enabled: bool):
    """Saves manual approval mode to database (persists after restart)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('manual_approval_mode', ?)",
        ("true" if enabled else "false",)
    )
    conn.commit()
    conn.close()

def get_protect_content() -> bool:
    """Returns whether forwarding is disabled (protect_content)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'protect_content'")
    result = cursor.fetchone()
    conn.close()
    return result is not None and (result[0] or "").lower() == "true"

def set_protect_content(enabled: bool):
    """Saves protect_content (disable forwarding) state to database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('protect_content', ?)",
        ("true" if enabled else "false",)
    )
    conn.commit()
    conn.close()

def _get_bot_setting(key: str) -> str:
    """Generic getter for bot_settings."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return (result[0] or "").strip() if result else ""

def _set_bot_setting(key: str, value: str):
    """Generic setter for bot_settings."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# --- /rules: photo + text (separate from /start) ---
def get_rules_photo_file_id() -> Optional[str]:
    return _get_bot_setting("rules_photo_file_id") or None

def set_rules_photo_file_id(file_id: str):
    _set_bot_setting("rules_photo_file_id", file_id.strip())

def get_rules_text() -> Optional[str]:
    v = _get_bot_setting("rules_text")
    return v if v else None

def set_rules_text(text: str):
    _set_bot_setting("rules_text", text)

# --- /start: photo + text (separate from /rules) ---
def get_start_photo_file_id() -> Optional[str]:
    return _get_bot_setting("start_photo_file_id") or None

def set_start_photo_file_id(file_id: str):
    _set_bot_setting("start_photo_file_id", file_id.strip())

def get_start_text() -> Optional[str]:
    v = _get_bot_setting("start_text")
    return v if v else None

def set_start_text(text: str):
    _set_bot_setting("start_text", text)

# --- Auth Group (Group Membership Verification) ---
def get_auth_group() -> tuple:
    """Returns (group_id, group_name) if set, else (None, None)."""
    group_id_str = _get_bot_setting("auth_group_id")
    group_name = _get_bot_setting("auth_group_name")
    
    if group_id_str:
        try:
            return int(group_id_str), group_name or "Oficial"
        except ValueError:
            return None, None
    return None, None

def set_auth_group(group_id: int, group_name: str):
    _set_bot_setting("auth_group_id", str(group_id))
    _set_bot_setting("auth_group_name", group_name)

def del_auth_group():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_settings WHERE key IN ('auth_group_id', 'auth_group_name')")
    conn.commit()
    conn.close()

# --- Sync Channel (Forwarding Broadcasts) ---
def get_sync_channel() -> Optional[int]:
    """Returns dynamic sync channel ID if set."""
    val = _get_bot_setting("sync_channel_id")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return None

def set_sync_channel(channel_id: int):
    """Sets dynamic sync channel ID."""
    _set_bot_setting("sync_channel_id", str(channel_id))

def del_sync_channel():
    """Removes dynamic sync channel ID."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_settings WHERE key = 'sync_channel_id'")
    conn.commit()
    conn.close()

# --- Capacity Limit ---
def get_capacity_limit() -> int:
    """Returns the max allowed users limit. 0 means unlimited."""
    limit_str = _get_bot_setting("capacity_limit")
    if limit_str:
        try:
            return int(limit_str)
        except ValueError:
            return 0
    return 0

def set_capacity_limit(limit: int):
    _set_bot_setting("capacity_limit", str(limit))

async def get_regular_users_count() -> int:
    """Count of approved non-VIP/non-Admin ACTIVE users (excludes inactive users past INACTIVITY_HOURS)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    inactive_threshold = datetime.now() - timedelta(hours=INACTIVITY_HOURS)
    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE approved = 1 AND is_banned = 0 AND is_vip = 0 AND is_admin = 0 AND datetime(last_active) > datetime(?)",
        (inactive_threshold.strftime('%Y-%m-%d %H:%M:%S'),)
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count

# --- Points and tag ---
def _update_tag_status(conn, cursor, user_id: int, points_val: int):
    has_tag = 1 if points_val >= TAG_THRESHOLD else 0
    cursor.execute("UPDATE users SET has_tag = ? WHERE user_id = ?", (has_tag, user_id))

async def add_points(user_id: int, delta: int) -> int:
    """Add delta to points; cannot go negative or above POINTS_MAX. Updates has_tag. Returns new total."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = MIN(?, MAX(0, COALESCE(points, 0) + ?)) WHERE user_id = ?", (POINTS_MAX, delta, user_id))
    cursor.execute("SELECT COALESCE(points, 0) FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    new_total = row[0] if row else 0
    _update_tag_status(conn, cursor, user_id, new_total)
    conn.commit()
    conn.close()
    return new_total

async def remove_points(user_id: int, amount: int) -> int:
    """Subtract amount from points (cannot go negative). Returns new total."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = MAX(0, COALESCE(points, 0) - ?) WHERE user_id = ?", (amount, user_id))
    cursor.execute("SELECT COALESCE(points, 0) FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    new_total = row[0] if row else 0
    _update_tag_status(conn, cursor, user_id, new_total)
    conn.commit()
    conn.close()
    return new_total

async def set_points(user_id: int, value: int) -> int:
    """Set user points (between 0 and POINTS_MAX). Updates has_tag. Returns set value."""
    value = max(0, min(POINTS_MAX, value))
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = ? WHERE user_id = ?", (value, user_id))
    _update_tag_status(conn, cursor, user_id, value)
    conn.commit()
    conn.close()
    return value

async def get_user_points(user_id: int) -> int:
    """Returns user points."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(points, 0) FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

async def get_reaction(broadcast_message_id: int, target_user_id: int, reactor_user_id: int) -> Optional[str]:
    """Returns 'fire', 'disgust', or None."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT reaction_type FROM reactions WHERE broadcast_message_id = ? AND target_user_id = ? AND reactor_user_id = ?",
        (broadcast_message_id, target_user_id, reactor_user_id)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

async def set_reaction(broadcast_message_id: int, target_user_id: int, reactor_user_id: int, reaction_type: str):
    """Records reaction (fire/disgust). One per user per message."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO reactions (broadcast_message_id, target_user_id, reactor_user_id, reaction_type, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (broadcast_message_id, target_user_id, reactor_user_id, reaction_type))
    conn.commit()
    conn.close()

async def save_message_mapping(broadcast_msg_id: int, target_user_id: int, original_sender_id: int, original_msg_id: int):
    """Save mapping: sent message -> user -> original sender"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO message_mapping 
        (broadcast_message_id, target_user_id, original_sender_id, original_message_id)
        VALUES (?, ?, ?, ?)
    """, (broadcast_msg_id, target_user_id, original_sender_id, original_msg_id))
    conn.commit()
    conn.close()

async def get_message_id_for_user(original_msg_id: int, original_sender_id: int, target_user_id: int) -> Optional[int]:
    """Find which msg_id was sent to a specific user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT broadcast_message_id FROM message_mapping
        WHERE original_message_id = ? AND original_sender_id = ? AND target_user_id = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (original_msg_id, original_sender_id, target_user_id))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

async def is_duplicate_media(user_id: int, file_unique_id: str, hours: int = 72) -> bool:
    """Check if THIS user has already sent this media"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    time_limit = datetime.now() - timedelta(hours=hours)
    cursor.execute("""
        SELECT COUNT(*) FROM media_history
        WHERE user_id = ? AND file_unique_id = ? AND datetime(timestamp) > datetime(?)
    """, (user_id, file_unique_id, time_limit.strftime('%Y-%m-%d %H:%M:%S')))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

async def increment_user_duplicate_count(user_id: int) -> int:
    """Increment duplicate counter"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET duplicates_blocked = COALESCE(duplicates_blocked, 0) + 1
        WHERE user_id = ?
    """, (user_id,))
    cursor.execute("SELECT COALESCE(duplicates_blocked, 0) FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.commit()
    conn.close()
    return result[0] if result else 0

async def get_user_duplicate_count(user_id: int) -> int:
    """Returns total duplicates blocked"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(duplicates_blocked, 0) FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

async def get_top_duplicate_users(limit: int = 20) -> List[Dict]:
    """Top users with duplicates blocked"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, first_name, COALESCE(duplicates_blocked, 0) as dupes, is_vip, is_admin
        FROM users
        WHERE COALESCE(duplicates_blocked, 0) > 0
        ORDER BY duplicates_blocked DESC
        LIMIT ?
    """, (limit,))
    results = cursor.fetchall()
    conn.close()
    return [{'user_id': r[0], 'first_name': r[1] or 'Unknown', 'duplicates_blocked': r[2], 'is_vip': bool(r[3]), 'is_admin': bool(r[4])} for r in results]

async def clean_duplicate_media() -> int:
    """Remove duplicates keeping first occurrence per user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM media_history
        WHERE id NOT IN (
            SELECT MIN(id) FROM media_history GROUP BY user_id, file_unique_id
        )
    """)
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

async def add_approved_user(user_id: int, username: str = None, first_name: str = None):
    """Add or update user (does not overwrite is_admin/is_vip if manually set)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    is_admin = 1 if user_id in ADMIN_IDS else 0
    is_vip = is_admin
    
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, is_admin, is_vip, approved, last_active)
        VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(?, username),
            first_name = COALESCE(?, first_name),
            is_admin = COALESCE(is_admin, ?),
            is_vip = COALESCE(is_vip, ?),
            approved = 1,
            last_active = CURRENT_TIMESTAMP
    """, (user_id, username, first_name, is_admin, is_vip, username, first_name, is_admin, is_vip))
    
    conn.commit()
    conn.close()

async def remove_approved_user(user_id: int):
    """Remove approval"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET approved = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def is_authorized(user_id: int) -> bool:
    """Check if user is authorized"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT approved, is_banned FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return False
    approved, is_banned = result
    return approved == 1 and is_banned == 0

async def update_user_activity(user_id: int, username: str = None, first_name: str = None):
    """Update activity and reset warnings"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET
            last_active = CURRENT_TIMESTAMP,
            username = COALESCE(?, username),
            first_name = COALESCE(?, first_name),
            inactivity_warnings = 0,
            last_72h_notified = NULL
        WHERE user_id = ?
    """, (username, first_name, user_id))
    conn.commit()
    conn.close()

async def get_user_details(user_id: int) -> Optional[Dict]:
    """Returns user details"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, username, first_name, is_vip, is_admin, last_active, is_banned, ban_reason,
               COALESCE(inactivity_warnings, 0), COALESCE(duplicates_blocked, 0), joined_date,
               COALESCE(points, 0), COALESCE(has_tag, 0)
        FROM users WHERE user_id = ?
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return None
    return {
        'user_id': result[0],
        'username': result[1],
        'first_name': result[2] or 'Unknown',
        'is_vip': bool(result[3]),
        'is_admin': bool(result[4]),
        'last_active': result[5],
        'is_banned': bool(result[6]),
        'ban_reason': result[7],
        'inactivity_warnings': result[8],
        'duplicates_blocked': result[9],
        'joined_date': result[10],
        'points': result[11],
        'has_tag': bool(result[12])
    }

async def get_all_approved_users() -> List[Dict]:
    """List all approved users - ORDER: Admin > VIP > Alphabetical"""
    import re
    import unicodedata
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, username, first_name, is_vip, is_admin, COALESCE(has_tag, 0)
        FROM users
        WHERE approved = 1 AND is_banned = 0
    """)
    results = cursor.fetchall()
    conn.close()
    
    # Convert to list of dictionaries
    users = []
    for r in results:
        users.append({
            'user_id': r[0],
            'username': r[1],
            'first_name': r[2] or 'Unknown',
            'is_vip': bool(r[3]),
            'is_admin': bool(r[4]),
            'has_tag': bool(r[5])
        })
    
    # Function to normalize names
    def normalize_name(name):
        cleaned = re.sub(r'[^\w\s]', '', name)
        normalized = unicodedata.normalize('NFKD', cleaned)
        ascii_name = normalized.encode('ascii', 'ignore').decode('ascii')
        return ascii_name.strip().lower() or 'zzz'

    # Sort: admin > vip > peek > regular users + alphabetical
    users.sort(key=lambda x: (
        not x['is_admin'],
        not x['is_vip'],
        not x.get('has_tag', False),
        normalize_name(x['first_name'])
    ))
    return users

async def get_active_users_for_broadcast() -> List[int]:
    """Returns active user IDs for broadcast"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    inactive_threshold = datetime.now() - timedelta(hours=INACTIVITY_HOURS)
    cursor.execute("""
        SELECT user_id FROM users
        WHERE approved = 1 AND is_banned = 0
        AND (is_vip = 1 OR is_admin = 1 OR datetime(last_active) > datetime(?))
    """, (inactive_threshold.strftime('%Y-%m-%d %H:%M:%S'),))
    results = cursor.fetchall()
    conn.close()
    return [r[0] for r in results]

async def set_user_vip_status(user_id: int, is_vip: bool):
    """Set VIP status"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (1 if is_vip else 0, user_id))
    conn.commit()
    conn.close()

async def set_user_admin_status(user_id: int, is_admin: bool):
    """Set Admin status"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_admin = ?, is_vip = ? WHERE user_id = ?", (1 if is_admin else 0, 1 if is_admin else 0, user_id))
    conn.commit()
    conn.close()

async def get_vip_users_count() -> int:
    """Count VIPs"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1 AND is_banned = 0")
    count = cursor.fetchone()[0]
    conn.close()
    return count

async def ban_user_permanent(user_id: int, reason: str = "No reason"):
    """Permanently ban user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 1, ban_reason = ?, approved = 0 WHERE user_id = ?", (reason, user_id))
    conn.commit()
    conn.close()

async def unban_user_permanent(user_id: int):
    """Remove ban from user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 0, ban_reason = NULL, approved = 1, inactivity_warnings = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return bool(result[0]) if result else False

async def get_banned_users_count() -> int:
    """Count banned users"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    count = cursor.fetchone()[0]
    conn.close()
    return count

async def get_all_banned_users() -> List[Dict]:
    """List banned users"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, ban_reason FROM users WHERE is_banned = 1 ORDER BY user_id DESC")
    results = cursor.fetchall()
    conn.close()
    return [{'user_id': r[0], 'username': r[1], 'first_name': r[2] or 'Unknown', 'ban_reason': r[3] or 'No reason'} for r in results]

async def search_users_by_name(search_term: str) -> List[Dict]:
    """Search users by name or username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    search_pattern = f"%{search_term}%"
    cursor.execute("""
        SELECT user_id, username, first_name, is_vip, is_admin, last_active, is_banned, COALESCE(duplicates_blocked, 0), joined_date, COALESCE(points, 0), COALESCE(has_tag, 0)
        FROM users
        WHERE LOWER(first_name) LIKE LOWER(?) OR LOWER(username) LIKE LOWER(?)
        ORDER BY is_admin DESC, is_vip DESC, last_active DESC
        LIMIT 20
    """, (search_pattern, search_pattern))
    results = cursor.fetchall()
    conn.close()
    return [{'user_id': r[0], 'username': r[1], 'first_name': r[2] or 'Unknown', 'is_vip': bool(r[3]), 'is_admin': bool(r[4]), 'last_active': r[5], 'is_banned': bool(r[6]), 'duplicates_blocked': r[7], 'joined_date': r[8], 'points': r[9], 'has_tag': bool(r[10])} for r in results]

async def increment_inactivity_warning(user_id: int) -> int:
    """Increment inactivity warning"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET inactivity_warnings = COALESCE(inactivity_warnings, 0) + 1 WHERE user_id = ?", (user_id,))
    cursor.execute("SELECT COALESCE(inactivity_warnings, 0) FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.commit()
    conn.close()
    return result[0] if result else 0

async def reset_inactivity_warnings(user_id: int):
    """Reset inactivity warnings"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET inactivity_warnings = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def get_users_to_warn_71h() -> List[int]:
    """Users to warn (1h before inactivity threshold: INACTIVITY_HOURS - 1, e.g. 23h)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    warn_hours = max(1, INACTIVITY_HOURS - 1)
    warn_time = datetime.now() - timedelta(hours=warn_hours)
    inactive_time = datetime.now() - timedelta(hours=INACTIVITY_HOURS)
    cursor.execute("""
        SELECT user_id FROM users
        WHERE approved = 1 AND is_banned = 0 AND is_vip = 0 AND is_admin = 0
        AND datetime(last_active) <= datetime(?)
        AND datetime(last_active) > datetime(?)
        AND COALESCE(inactivity_warnings, 0) = 0
    """, (warn_time.strftime('%Y-%m-%d %H:%M:%S'), inactive_time.strftime('%Y-%m-%d %H:%M:%S')))
    results = cursor.fetchall()
    conn.close()
    return [r[0] for r in results]

async def get_users_to_notify_72h() -> List[int]:
    """Users inactive 72h - Notify only ONCE"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    inactive_time = datetime.now() - timedelta(hours=INACTIVITY_HOURS)
    cursor.execute("""
        SELECT user_id FROM users
        WHERE approved = 1 AND is_banned = 0 AND is_vip = 0 AND is_admin = 0
        AND datetime(last_active) <= datetime(?)
        AND (last_72h_notified IS NULL OR datetime(last_72h_notified) < datetime(last_active))
    """, (inactive_time.strftime('%Y-%m-%d %H:%M:%S'),))
    results = cursor.fetchall()
    conn.close()
    return [r[0] for r in results]

async def mark_user_72h_notified(user_id: int):
    """Mark that user was notified about 72h inactivity"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_72h_notified = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def add_media_to_history(messages: list):
    """Add media to history (for duplicate detection)."""
    if not messages:
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    for msg in messages:
        media_type = None
        file_id = None
        file_unique_id = None
        
        if msg.photo:
            media_type, file_id, file_unique_id = 'photo', msg.photo.file_id, msg.photo.file_unique_id
        elif msg.video:
            media_type, file_id, file_unique_id = 'video', msg.video.file_id, msg.video.file_unique_id
        elif msg.animation:
            media_type, file_id, file_unique_id = 'animation', msg.animation.file_id, msg.animation.file_unique_id
        elif msg.document:
            media_type, file_id, file_unique_id = 'document', msg.document.file_id, msg.document.file_unique_id
        elif msg.audio:
            media_type, file_id, file_unique_id = 'audio', msg.audio.file_id, msg.audio.file_unique_id
        
        if media_type and file_id and file_unique_id:
            cursor.execute("""
                INSERT INTO media_history (user_id, media_type, file_id, file_unique_id, caption)
                VALUES (?, ?, ?, ?, ?)
            """, (msg.from_user.id, media_type, file_id, file_unique_id, msg.caption or ''))
    
    conn.commit()
    conn.close()

async def get_media_stats() -> Dict[str, int]:
    """Media statistics"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT media_type, COUNT(*) FROM media_history GROUP BY media_type")
    results = cursor.fetchall()
    conn.close()
    
    stats = {'photo': 0, 'video': 0, 'animation': 0, 'document': 0, 'audio': 0}
    for media_type, count in results:
        if media_type in stats:
            stats[media_type] = count
    return stats

async def add_pending_approval(user_id: int, username: str = None, first_name: str = None):
    """Add to pending approvals"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO pending_approvals (user_id, username, first_name, requested_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, username, first_name))
    conn.commit()
    conn.close()

async def remove_pending_approval(user_id: int):
    """Remove from pending approvals"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pending_approvals WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def is_pending_approval(user_id: int) -> bool:
    """Check if user is pending approval"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pending_approvals WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

async def get_all_pending_approvals() -> List[Dict]:
    """List pending approvals"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, requested_at FROM pending_approvals ORDER BY requested_at ASC")
    results = cursor.fetchall()
    conn.close()
    return [{'user_id': r[0], 'username': r[1], 'first_name': r[2] or 'Unknown', 'requested_at': r[3]} for r in results]

async def get_user_media_stats(user_id: int) -> Dict[str, int]:
    """Returns media statistics for a specific user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT media_type, COUNT(*) 
        FROM media_history 
        WHERE user_id = ? 
        GROUP BY media_type
    """, (user_id,))
    results = cursor.fetchall()
    conn.close()
    
    stats = {'photo': 0, 'video': 0, 'animation': 0, 'document': 0, 'audio': 0}
    for media_type, count in results:
        if media_type in stats:
            stats[media_type] = count
    
    stats['total'] = sum(stats.values())
    return stats

async def get_all_broadcast_recipients(original_sender_id: int, original_message_id: int) -> List[Dict]:
    """Returns all users who received a specific broadcast message"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT target_user_id, broadcast_message_id
        FROM message_mapping
        WHERE original_sender_id = ? AND original_message_id = ?
    """, (original_sender_id, original_message_id))
    results = cursor.fetchall()
    conn.close()
    return [{'user_id': r[0], 'message_id': r[1]} for r in results]
    
async def get_inactive_users_3days() -> List[Dict]:
    """Returns non-VIP/Admin users inactive for SCAN_INACTIVE_DAYS (default 3) days (no photo/video).
    Excludes users already handled by 24h inactivity (last_72h_notified set = already notified and removed)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    inactive_threshold = datetime.now() - timedelta(days=SCAN_INACTIVE_DAYS)
    
    cursor.execute("""
        SELECT user_id, username, first_name, last_active, 
               COALESCE(duplicates_blocked, 0) as dupes
        FROM users
        WHERE approved = 1 
        AND is_banned = 0
        AND is_vip = 0
        AND is_admin = 0
        AND datetime(last_active) < datetime(?)
        AND last_72h_notified IS NULL
        ORDER BY datetime(last_active) ASC
    """, (inactive_threshold.strftime('%Y-%m-%d %H:%M:%S'),))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'user_id': r[0],
        'username': r[1],
        'first_name': r[2] or 'Unknown',
        'last_active': r[3],
        'duplicates_blocked': r[4]
    } for r in results]

logger.info("Database module loaded - V2.8 Reply support")
