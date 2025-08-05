import json
import os
import logging

# Configuration
COLLISION_LOG_FILE = 'collision_log.json'
MAX_LOG_ENTRIES = 1000  # Maximum number of entries to keep

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_collision_log():
    """Load collision log from file, create empty list if file doesn't exist"""
    if os.path.exists(COLLISION_LOG_FILE):
        try:
            with open(COLLISION_LOG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Could not read {COLLISION_LOG_FILE}, starting with empty log")
            return []
    else:
        return []

def save_collision_log(collision_data):
    """Save collision log to file"""
    try:
        with open(COLLISION_LOG_FILE, 'w') as f:
            json.dump(collision_data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving collision log: {str(e)}")
        return False

def cleanup_old_entries(collision_data):
    """Remove old entries if log exceeds maximum size"""
    if len(collision_data) > MAX_LOG_ENTRIES:
        # Keep only the most recent entries
        collision_data = collision_data[-MAX_LOG_ENTRIES:]
        logger.info(f"Cleaned up collision log, keeping {MAX_LOG_ENTRIES} most recent entries")
    return collision_data