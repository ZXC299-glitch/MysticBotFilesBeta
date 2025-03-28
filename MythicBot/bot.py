# bot.py (Snippets)
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# --- Bot Configuration ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
BOT_PREFIX = "z."

# Define colors centrally - Make sure this matches or is accessible by cogs
EMBED_COLORS = {
    "default": discord.Color.blue(),
    "success": discord.Color.green(),
    "error": discord.Color.red(),
    "warning": discord.Color.orange(),
    "info": discord.Color.blurple(), # Added info color
}

# --- Intents --- (Ensure necessary intents are enabled)
intents = discord.Intents.default()
intents.members = True          # Crucial for moderation targets, member events
intents.message_content = True  # For prefix commands
intents.guilds = True           # For guild-specific configs, guild info

# --- Bot Initialization ---
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None) # Use custom help

# --- Cog Loading ---
async def load_cogs():
    print("Loading cogs...")
    # Define the cogs you want to load
    cog_files = ['moderation.py', 'logging.py', 'verification.py', 'utility.py', 'fun.py'] # Add others as needed
    for filename in cog_files:
        cog_path = f'cogs.{filename[:-3]}'
        if os.path.exists(f'./cogs/{filename}') and filename != '__init__.py':
            try:
                await bot.load_extension(cog_path)
                print(f'  Successfully loaded cog: {cog_path}')
            except commands.ExtensionNotFound:
                 print(f'  ERROR: Cog file not found for {cog_path}. Skipping.')
            except commands.ExtensionAlreadyLoaded:
                 print(f'  INFO: Cog {cog_path} already loaded. Skipping.')
            except commands.NoEntryPointError:
                 print(f'  ERROR: Cog {cog_path} does not have a setup function. Skipping.')
            except Exception as e:
                print(f'  ERROR: Failed to load cog {cog_path}. Error: {e.__class__.__name__}: {e}')
        # else: # Optional: Notify if a file in the list doesn't exist
        #      if filename != '__init__.py': print(f'  WARNING: Cog file {filename} not found in cogs directory.')
    print("------ Cog loading finished ------")

# --- Run the Bot ---
async def main():
    if TOKEN is None:
        print("FATAL ERROR: Bot token not found in .env file.")
        return

    async with bot:
        await load_cogs() # Load cogs before starting
        try:
            await bot.start(TOKEN)
        # ... (rest of your error handling for startup) ...
        except Exception as e:
            print(f"FATAL ERROR during bot execution: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down.")
# ... (rest of bot.py) ...