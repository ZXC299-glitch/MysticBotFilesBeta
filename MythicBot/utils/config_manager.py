# utils/config_manager.py
import json
import os
import asyncio
from discord import Guild

CONFIG_DIR = "config"
_locks = {} # Dictionary to hold asyncio.Lock for each guild ID
_get_lock_lock = asyncio.Lock() # Lock for accessing the _locks dictionary itself

# Ensure config directory exists
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)

async def get_guild_lock(guild_id: int) -> asyncio.Lock:
    """Gets or creates an asyncio.Lock for a specific guild ID."""
    async with _get_lock_lock:
        if guild_id not in _locks:
            _locks[guild_id] = asyncio.Lock()
        return _locks[guild_id]

async def get_config(guild: Guild | int) -> dict:
    """Loads the configuration for a specific guild."""
    guild_id = guild.id if isinstance(guild, Guild) else guild
    filepath = os.path.join(CONFIG_DIR, f"{guild_id}.json")
    lock = await get_guild_lock(guild_id)

    async with lock:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return a default structure if file doesn't exist or is invalid
            return {
                "log_channel": None,
                "welcome_channel": None,
                "leave_channel": None,
                "verified_role": None,
                "mod_log_channel": None,
                "welcome_message": "Welcome {user.mention} to {server.name}!",
                "leave_message": "{user.name} has left {server.name}.",
                "warnings": {}, # { "user_id_str": [ { "mod_id": ..., "reason": ..., "timestamp": ... } ] }
                "warn_threshold": 3,
                "warn_action": "timeout", # none, timeout, kick, ban
                "warn_timeout_duration": "1h"
            }

async def save_config(guild: Guild | int, data: dict):
    """Saves the configuration for a specific guild."""
    guild_id = guild.id if isinstance(guild, Guild) else guild
    filepath = os.path.join(CONFIG_DIR, f"{guild_id}.json")
    lock = await get_guild_lock(guild_id)

    async with lock:
        try:
            # Create directory if it doesn't exist (should already, but safe)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            # Use indentation for readability
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"Error saving config for guild {guild_id}: {e}")
        except Exception as e:
            print(f"Unexpected error saving config for {guild_id}: {e}")