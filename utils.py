"""
Bot utilities
"""

import re
import time
from collections import defaultdict

# Rate limiting
user_rate_limits = defaultdict(list)

def check_rate_limit(user_id: int) -> bool:
    """Check rate limit"""
    from config import RATE_LIMIT, RATE_WINDOW

    now = time.time()

    # Remove old timestamps
    user_rate_limits[user_id] = [
        t for t in user_rate_limits[user_id]
        if now - t < RATE_WINDOW
    ]

    # Check limit
    if len(user_rate_limits[user_id]) >= RATE_LIMIT:
        return False

    # Add current timestamp
    user_rate_limits[user_id].append(now)
    return True

def strip_sender_info(text: str) -> str:
    """Remove first line if it looks like broadcast sender info (Name[ADMIN], Name[VIP], etc)."""
    if not text or not text.strip():
        return text.strip() if text else text
    lines = text.strip().split("\n", 1)
    first_line = lines[0].strip()
    rest = lines[1].strip() if len(lines) > 1 else ""
    if re.match(r"^(\*\*[^*]*\*\*|[^\n\[]+)\s*\[(?:ADMIN|VIP|TAG[a-zA-Z0-9]*)\](?::\s*)?$", first_line):
        if (rest.startswith("-") or rest.startswith("─")) and "\n" in rest:
            second_line, new_rest = rest.split("\n", 1)
            if re.match(r"^[─-]+$", second_line.strip()):
                return new_rest.strip()
        elif re.match(r"^[─-]+$", rest.strip()):
            return ""
        return rest
    return text.strip()

def has_forbidden_content(text: str) -> bool:
    """Check if text contains forbidden links"""
    if not text:
        return False

    text_lower = text.lower()
    forbidden = [
        'http://', 'https://', 'www.',
        't.me/', 'telegram.me/',
        '@channel', '@group'
    ]

    return any(pattern in text_lower for pattern in forbidden)

async def get_sender_info(user, is_vip: bool = False, is_admin: bool = False, has_tag: bool = False) -> str:
    """Format sender information - Tags (Admin, VIP, custom tag)"""
    from config import TAG_NAME
    name = user.first_name

    tag = ""
    if is_admin:
        tag = " [ADMIN]"
    elif is_vip:
        tag = " [VIP]"
    elif has_tag:
        tag = f" [{TAG_NAME}]"

    raw_text_length = len(name) + len(tag)
    dashed_line = "─" * raw_text_length

    return f"**{name}**{tag}\n{dashed_line}"
