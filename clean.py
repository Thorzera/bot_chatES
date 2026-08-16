import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()
DB_FILE = os.getenv("DB_FILE", "data/bot.db")
# Comma-separated user/channel IDs to remove (e.g. inaccessible channels). Empty = skip.
CLEAN_EXCLUDE_IDS = os.getenv("CLEAN_EXCLUDE_IDS", "-1003137344058")

def clean_database():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        print("🔍 Searching for invalid IDs...")
        
        # 1. Delete huge positive IDs (likely channels without minus sign)
        cursor.execute("DELETE FROM users WHERE user_id > 100000000000")
        print(f"🗑️ Deleted {cursor.rowcount} corrupted IDs (wrong format).")

        # 2. Remove IDs configured in CLEAN_EXCLUDE_IDS (comma-separated)
        if CLEAN_EXCLUDE_IDS.strip():
            for uid_str in CLEAN_EXCLUDE_IDS.split(","):
                try:
                    uid = int(uid_str.strip())
                    cursor.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                    if cursor.rowcount > 0:
                        print(f"🗑️ Deleted user/channel ID: {uid}")
                except ValueError:
                    pass

        conn.commit()
        conn.close()
        print("✅ Database cleaned successfully!")
        
    except Exception as e:
        print(f"❌ Error cleaning database: {e}")

if __name__ == "__main__":
    clean_database()
