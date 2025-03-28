# cogs/moderation.py
import discord
from discord.ext import commands
import datetime
import time
import asyncio # Needed for sleep in clear command confirmation

# Import necessary components from other files in the project
# Ensure these paths/imports match your project structure
try:
    from bot import EMBED_COLORS # Assuming EMBED_COLORS is defined in your main bot.py
except ImportError:
    # Fallback or default colors if bot.py structure differs
    EMBED_COLORS = {
        "default": discord.Color.blue(), "success": discord.Color.green(),
        "error": discord.Color.red(), "warning": discord.Color.orange(),
        "info": discord.Color.blurple(),
    }
try:
    from utils.config_manager import get_config, save_config
except ImportError:
    # Define dummy functions if utils are missing, to avoid crashing the cog load
    # This allows testing the cog structure even if config management fails
    print("WARNING: Could not import config_manager. Using dummy functions.")
    async def get_config(*args): return {}
    async def save_config(*args): pass
try:
    from utils.duration_parser import parse_duration
except ImportError:
    print("WARNING: Could not import duration_parser. Timeout commands may fail.")
    def parse_duration(*args): return None


class Moderation(commands.Cog):
    """Commands for server moderation: kick, ban, timeout, warnings, etc."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Helper Functions ---

    async def _get_log_function(self):
        """Safely gets the log_event function from the Logging cog, if available."""
        logging_cog = self.bot.get_cog("Logging")
        if logging_cog and hasattr(logging_cog, "log_event"):
            return logging_cog.log_event
        else:
            # Return a dummy function that does nothing if Logging cog isn't loaded
            async def dummy_log(*args, **kwargs):
                # print("Debug: Logging cog not found, skipping log event.") # Optional debug print
                pass
            return dummy_log

    def _create_mod_log_embed(self, action: str, target: discord.Member | discord.User, moderator: discord.Member, reason: str, duration: str | None = None, color = None, additional_fields: list[tuple[str, str]] | None = None) -> discord.Embed:
        """Creates a standardized embed for moderation logs."""
        if color is None: color = EMBED_COLORS.get("warning", discord.Color.orange()) # Default color

        embed = discord.Embed(
            title=f"Moderation Action: {action.title()}",
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        # Use display_avatar which might be server-specific
        embed.set_author(name=f"{target.name}#{target.discriminator} (ID: {target.id})", icon_url=target.display_avatar.url)
        embed.add_field(name="User", value=target.mention, inline=True)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)

        # Add reason, ensuring it fits
        reason_value = reason if reason else "No reason provided."
        if len(reason_value) > 1024:
            reason_value = reason_value[:1020] + "..." # Truncate if too long
        embed.add_field(name="Reason", value=reason_value, inline=False)

        # Add any extra fields provided
        if additional_fields:
            for name, value in additional_fields:
                # Ensure value also fits
                if len(value) > 1024: value = value[:1020] + "..."
                embed.add_field(name=name, value=value, inline=True) # Or False depending on desired layout

        return embed

    async def _check_moderation_permissions(self, ctx: commands.Context, member: discord.Member) -> bool:
        """
        Checks if a moderation action can be performed against a member.
        Returns True if okay, False otherwise (and sends an error message to ctx).
        Checks: self-moderation, bot owner, bot hierarchy, moderator hierarchy.
        """
        # 1. Cannot moderate self
        if member == ctx.author:
            await ctx.send(embed=discord.Embed(description="❌ You cannot moderate yourself.", color=EMBED_COLORS.get("error", discord.Color.red())))
            return False

        # 2. Cannot moderate bot owner (Good practice)
        if await self.bot.is_owner(member):
             await ctx.send(embed=discord.Embed(description="❌ You cannot moderate the bot owner.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return False

        # 3. Bot hierarchy check: Bot's top role must be higher than member's top role
        # Need to ensure ctx.guild.me is available (e.g., command has @commands.guild_only())
        if not ctx.guild.me: # Should not happen in guild_only commands but safety check
            print(f"Warning: ctx.guild.me is None in _check_moderation_permissions for guild {ctx.guild.id}")
            await ctx.send(embed=discord.Embed(description="⚙️ Internal check failed: Could not determine my own roles.", color=EMBED_COLORS.get("error", discord.Color.red())))
            return False
        if ctx.guild.me.top_role <= member.top_role:
            await ctx.send(embed=discord.Embed(description=f"❌ I cannot moderate {member.mention} because their highest role (`{member.top_role.name}`) is higher than or equal to mine (`{ctx.guild.me.top_role.name}`).", color=EMBED_COLORS.get("error", discord.Color.red())))
            return False

        # 4. Moderator hierarchy check: Moderator's top role must be higher than member's top role (unless moderator is owner)
        if ctx.author != ctx.guild.owner and ctx.author.top_role <= member.top_role:
            await ctx.send(embed=discord.Embed(description=f"❌ You cannot moderate {member.mention} because their role (`{member.top_role.name}`) is higher than or equal to yours (`{ctx.author.top_role.name}`).", color=EMBED_COLORS.get("error", discord.Color.red())))
            return False

        # 5. Specific check for Admins (Timeout command itself fails this via API, but good for kick/ban)
        # Consider if you *want* non-owners to kick/ban admins. Often, you don't.
        # if member.guild_permissions.administrator and ctx.author != ctx.guild.owner:
        #     await ctx.send(embed=discord.Embed(description="❌ You cannot moderate an Administrator unless you are the server owner.", color=EMBED_COLORS.get("error", discord.Color.red())))
        #     return False

        return True # All checks passed

    async def _send_dm_notification(self, member: discord.Member | discord.User, title: str, guild_name: str, reason: str, moderator: discord.Member | discord.User, duration: str | None = None, expires_timestamp: int | None = None) -> bool:
        """Attempts to send a DM notification to the user being moderated. Returns True if successful."""
        # Don't try to DM bots
        if member.bot: return False
        try:
            embed = discord.Embed(
                title=title,
                description=f"You have received a moderation action in **{guild_name}**.",
                color=EMBED_COLORS.get("warning", discord.Color.orange())
            )
            if duration:
                embed.add_field(name="Duration", value=duration, inline=True)
            if expires_timestamp:
                 # Display relative time AND full date/time for clarity
                 embed.add_field(name="Expires", value=f"<t:{expires_timestamp}:F> (<t:{expires_timestamp}:R>)", inline=True)
            embed.add_field(name="Reason", value=reason if reason else "No reason provided.", inline=False)
            embed.add_field(name="Moderator", value=moderator.mention, inline=False)
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

            await member.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            # User has DMs disabled, blocked the bot, or another issue occurred
            print(f"Failed to send DM notification to {member.name} ({member.id}): {e}")
            return False

    # --- Moderation Commands ---

    @commands.command(name='kick', help='Kicks a user from the server.')
    @commands.has_permissions(kick_members=True)
    @commands.guild_only()
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None):
        """Kicks a member from the server.
        Usage: z.kick @User [Optional Reason]
        """
        reason = reason or "No reason provided"
        if not await self._check_moderation_permissions(ctx, member):
            return # Stop if hierarchy/permission checks fail

        log_func = await self._get_log_function()

        # Attempt to notify user via DM before kicking
        dm_sent = await self._send_dm_notification(member, "Kicked", ctx.guild.name, reason, ctx.author)

        try:
            # Perform the kick action with reason for audit log
            mod_reason_audit = f"Kicked by {ctx.author.name} ({ctx.author.id}). Reason: {reason}"
            await member.kick(reason=mod_reason_audit)

            # Send confirmation to the channel
            confirm_embed = discord.Embed(
                description=f"✅ **Kicked** {member.mention} ({member.display_name})",
                color=EMBED_COLORS.get("success", discord.Color.green())
            )
            confirm_embed.add_field(name="Reason", value=reason, inline=False)
            footer_text = f"Kicked by {ctx.author.display_name}"
            if not dm_sent: footer_text += " | ⚠️ Failed to notify user via DM."
            confirm_embed.set_footer(text=footer_text)
            await ctx.send(embed=confirm_embed)

            # Log the action
            log_embed = self._create_mod_log_embed("Kick", member, ctx.author, reason, color=EMBED_COLORS.get("warning", discord.Color.orange()))
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"User {member.name} kicked by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I don't have the 'Kick Members' permission.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during kick: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during kick command for {member.name}: {e}")


    @commands.command(name='ban', help='Bans a user from the server (by ID or mention).')
    @commands.has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx: commands.Context, user: discord.User, *, reason: str | None = None):
        """Bans a user. Works even if they aren't in the server (using ID).
        Usage: z.ban <@User|UserID> [Optional Reason]
        """
        reason = reason or "No reason provided"
        # Try to get member object for checks if user is currently in the server
        member = ctx.guild.get_member(user.id)
        if member:
             # Perform hierarchy checks only if the user is currently a member
             if not await self._check_moderation_permissions(ctx, member):
                 return

        log_func = await self._get_log_function()
        dm_sent = False

        # Attempt DM only if they are currently a member
        if member:
             dm_sent = await self._send_dm_notification(member, "Banned", ctx.guild.name, reason, ctx.author)

        try:
            # Perform the ban using the user object (works with ID)
            mod_reason_audit = f"Banned by {ctx.author.name} ({ctx.author.id}). Reason: {reason}"
            # delete_message_days=0 means don't delete messages. Set to 1-7 to delete recent messages.
            await ctx.guild.ban(user, reason=mod_reason_audit, delete_message_days=0)

            # Send confirmation to the channel
            confirm_embed = discord.Embed(
                description=f"✅ **Banned** {user.mention} ({user.name}#{user.discriminator})",
                color=EMBED_COLORS.get("error", discord.Color.red()) # Use error color for ban
            )
            confirm_embed.add_field(name="Reason", value=reason, inline=False)
            footer_text = f"Banned by {ctx.author.display_name}"
            if member and not dm_sent: footer_text += " | ⚠️ Failed to notify user via DM."
            elif not member: footer_text += " | User was not in the server."
            confirm_embed.set_footer(text=footer_text)
            await ctx.send(embed=confirm_embed)

            # Log the action
            log_embed = self._create_mod_log_embed("Ban", user, ctx.author, reason, color=EMBED_COLORS.get("error", discord.Color.red()))
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"User {user.name} banned by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I don't have the 'Ban Members' permission.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during ban: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during ban command for {user.name}: {e}")


    @commands.command(name='unban', help='Unbans a user from the server using their ID.')
    @commands.has_permissions(ban_members=True) # Requires ban perms to unban
    @commands.guild_only()
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str | None = None):
        """Unbans a user using their User ID.
        Usage: z.unban <UserID> [Optional Reason]
        """
        reason = reason or "No reason provided"
        log_func = await self._get_log_function()

        # Fetch the user object using the ID
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            await ctx.send(embed=discord.Embed(description=f"❌ User with ID `{user_id}` not found.", color=EMBED_COLORS.get("error", discord.Color.red())))
            return
        except Exception as e:
             await ctx.send(embed=discord.Embed(description=f"❗ An error occurred fetching user info: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
             print(f"Error fetching user info in unban: {e}")
             return

        # Check if the user is actually banned before trying to unban
        try:
            await ctx.guild.fetch_ban(discord.Object(id=user_id))
        except discord.NotFound:
            # User wasn't banned, inform the moderator
            await ctx.send(embed=discord.Embed(description=f"ℹ️ User {user.mention} (`{user_id}`) is not currently banned in this server.", color=EMBED_COLORS.get("info", discord.Color.blue())))
            return # Stop execution as there's nothing to unban
        except discord.Forbidden:
             # Bot lacks permission to view the ban list
             await ctx.send(embed=discord.Embed(description="❌ **Error:** I need the 'Ban Members' permission to check the ban list.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return
        except Exception as e: # Catch other potential errors during fetch_ban
             await ctx.send(embed=discord.Embed(description=f"❗ An error occurred checking ban status: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
             print(f"Error checking ban status in unban: {e}")
             return

        # If the user *is* banned, proceed with unban
        try:
            mod_reason_audit = f"Unbanned by {ctx.author.name} ({ctx.author.id}). Reason: {reason}"
            await ctx.guild.unban(user, reason=mod_reason_audit)

            # Send confirmation to the channel
            confirm_embed = discord.Embed(
                description=f"✅ **Unbanned** {user.mention} ({user.name}#{user.discriminator})",
                color=EMBED_COLORS.get("success", discord.Color.green())
            )
            confirm_embed.add_field(name="Reason", value=reason, inline=False)
            confirm_embed.set_footer(text=f"Unbanned by {ctx.author.display_name}")
            await ctx.send(embed=confirm_embed) # Corrected: was sending embed=embed

            # Log the action
            log_embed = self._create_mod_log_embed("Unban", user, ctx.author, reason, color=EMBED_COLORS.get("success", discord.Color.green()))
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"User {user.name} ({user_id}) unbanned by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

        except discord.Forbidden:
            # This might happen if permissions changed between checking ban list and unbanning
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I don't have the 'Ban Members' permission to unban.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during unban: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during unban command for {user.name}: {e}")


    @commands.command(name='timeout', aliases=['mute'], help='Times out a user (max 28 days).')
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration_str: str, *, reason: str | None = None):
        """Times out a member. Duration examples: 10s, 5m, 1h, 3d.
        Usage: z.timeout @User <duration> [Optional Reason]
        """
        reason = reason or "No reason provided"
        if not await self._check_moderation_permissions(ctx, member):
            return

        # Admins cannot be timed out by API (this check is redundant as API handles it, but good for user feedback)
        if member.guild_permissions.administrator:
             await ctx.send(embed=discord.Embed(description="❌ Administrators cannot be timed out.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return

        duration = parse_duration(duration_str)
        if duration is None or duration <= datetime.timedelta(seconds=0): # Also check for zero/negative
            await ctx.send(embed=discord.Embed(
                title="Invalid Duration",
                description=f"Could not parse `{duration_str}`. Use format like `10s`, `5m`, `1h`, `3d`. Max 28 days, must be positive.",
                color=EMBED_COLORS.get("error", discord.Color.red())
            ))
            return

        # Check if duration exceeds max (parse_duration should already do this, but double-check)
        if duration > datetime.timedelta(days=28):
             await ctx.send(embed=discord.Embed(description=f"❌ Duration `{duration_str}` is longer than the maximum 28 days.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return

        log_func = await self._get_log_function()
        until = discord.utils.utcnow() + duration
        until_timestamp = int(until.timestamp())

        # Attempt DM notification
        dm_sent = await self._send_dm_notification(member, "Timed Out", ctx.guild.name, reason, ctx.author, duration=duration_str, expires_timestamp=until_timestamp)

        try:
            # Perform the timeout
            mod_reason_audit = f"Timed out by {ctx.author.name} ({ctx.author.id}). Reason: {reason}"
            await member.timeout(duration, reason=mod_reason_audit)

             # Confirmation embed
            confirm_embed = discord.Embed(
                description=f"✅ **Timed Out** {member.mention} ({member.display_name})",
                color=EMBED_COLORS.get("success", discord.Color.green())
            )
            confirm_embed.add_field(name="Duration", value=duration_str, inline=True)
            confirm_embed.add_field(name="Expires", value=f"<t:{until_timestamp}:R>", inline=True) # Relative time
            confirm_embed.add_field(name="Reason", value=reason, inline=False)
            footer_text = f"Timed out by {ctx.author.display_name}"
            if not dm_sent: footer_text += " | ⚠️ Failed to notify user via DM."
            confirm_embed.set_footer(text=footer_text)
            await ctx.send(embed=confirm_embed)

            # Log embed
            log_embed = self._create_mod_log_embed("Timeout", member, ctx.author, reason, duration=duration_str, color=EMBED_COLORS.get("warning", discord.Color.orange()))
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"User {member.name} timed out by {ctx.author.name} in {ctx.guild.name} for {duration_str}. Reason: {reason}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I don't have the 'Moderate Members' permission to time out users.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except discord.HTTPException as e:
             # Catch potential API errors (e.g., duration slightly too long due to timing, or other API issues)
            await ctx.send(embed=discord.Embed(description=f"❌ An API error occurred: {e}. Ensure duration is valid (max 28 days).", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during timeout command (HTTPException) for {member.name}: {e}")
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during timeout: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during timeout command for {member.name}: {e}")


    @commands.command(name='untimeout', aliases=['unmute'], help='Removes a timeout from a user.')
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def untimeout(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None):
        """Removes timeout from a member.
        Usage: z.untimeout @User [Optional Reason]
        """
        reason = reason or "No reason provided"
        # Check if member is actually timed out before proceeding
        # member.timed_out_until is timezone-aware (UTC)
        if member.timed_out_until is None or member.timed_out_until <= discord.utils.utcnow():
             await ctx.send(embed=discord.Embed(description=f"ℹ️ {member.mention} is not currently timed out.", color=EMBED_COLORS.get("info", discord.Color.blue())))
             return

        # Hierarchy checks (maybe less strict for untimeout? Allow mods to remove timeouts they placed?)
        # For consistency, we use the same check for now.
        if not await self._check_moderation_permissions(ctx, member):
             return

        log_func = await self._get_log_function()

        try:
            # Remove the timeout by passing None or timedelta(0)
            mod_reason_audit = f"Timeout removed by {ctx.author.name} ({ctx.author.id}). Reason: {reason}"
            await member.timeout(None, reason=mod_reason_audit)

            # Confirmation embed
            confirm_embed = discord.Embed(
                description=f"✅ **Timeout Removed** for {member.mention} ({member.display_name})",
                color=EMBED_COLORS.get("success", discord.Color.green())
            )
            confirm_embed.add_field(name="Reason", value=reason, inline=False)
            confirm_embed.set_footer(text=f"Timeout removed by {ctx.author.display_name}")
            await ctx.send(embed=confirm_embed)

            # Log embed
            log_embed = self._create_mod_log_embed("Timeout Removed", member, ctx.author, reason, color=EMBED_COLORS.get("success", discord.Color.green()))
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"Timeout removed for {member.name} by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

             # Optionally DM the user that the timeout was removed
            try:
                await member.send(f"Your timeout in **{ctx.guild.name}** has been removed by {ctx.author.mention}. Reason: {reason}")
            except (discord.Forbidden, discord.HTTPException):
                pass # Ignore if DM fails, it's less critical for removal

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I don't have the 'Moderate Members' permission.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during untimeout: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during untimeout command for {member.name}: {e}")


    # --- Warning System ---

    @commands.command(name='warn', help='Warns a user and records it.')
    @commands.has_permissions(kick_members=True) # Or moderate_members, adjust perm level as desired
    @commands.guild_only()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None):
        """Warns a member. Triggers auto-action if threshold is met.
        Usage: z.warn @User <Reason>
        """
        if not reason:
             await ctx.send(embed=discord.Embed(description="❌ Please provide a reason for the warning.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return

        if not await self._check_moderation_permissions(ctx, member):
            return

        config = await get_config(ctx.guild.id)
        log_func = await self._get_log_function()
        user_id_str = str(member.id)
        # Use current unix timestamp as a simple, sortable ID for the warning
        warning_id = int(time.time())

        # Prepare warning entry
        warning_entry = {
            "moderator_id": ctx.author.id,
            "reason": reason,
            "timestamp": warning_id, # Timestamp also serves as the ID
            "id": warning_id
        }

        # Add warning to config (handle potential read/write issues)
        if "warnings" not in config or not isinstance(config["warnings"], dict):
            config["warnings"] = {} # Initialize if missing or wrong type
        if user_id_str not in config["warnings"]:
            config["warnings"][user_id_str] = []

        # Ensure the warnings for the user is a list
        if not isinstance(config["warnings"].get(user_id_str), list):
             config["warnings"][user_id_str] = []

        config["warnings"][user_id_str].append(warning_entry)
        # --- Save config ---
        await save_config(ctx.guild.id, config)
        # --- Config saved ---

        warnings_count = len(config["warnings"][user_id_str])

        # Confirmation embed
        confirm_embed = discord.Embed(
            description=f"⚠️ **Warned** {member.mention} ({member.display_name})",
            color=EMBED_COLORS.get("warning", discord.Color.orange())
        )
        confirm_embed.add_field(name="Reason", value=reason, inline=False)
        confirm_embed.set_footer(text=f"Warned by {ctx.author.display_name} | User now has {warnings_count} warning(s)")
        await ctx.send(embed=confirm_embed)

        # Log embed
        log_embed = self._create_mod_log_embed("Warn", member, ctx.author, reason, color=EMBED_COLORS.get("warning", discord.Color.orange()), additional_fields=[("Total Warnings", str(warnings_count))])
        await log_func(ctx.guild, log_embed, log_type='mod_log')
        print(f"User {member.name} warned by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}. Total warnings: {warnings_count}")

         # Try to DM the user
        dm_sent = await self._send_dm_notification(member, "Warning Received", ctx.guild.name, reason, ctx.author)
        if not dm_sent:
             # Send a quick follow-up in channel if DM failed
             try:
                await ctx.send(f"⚠️ Could not notify {member.mention} via DM.", allowed_mentions=discord.AllowedMentions.none(), delete_after=10)
             except discord.Forbidden: pass # Ignore if can't send followup

        # --- Auto-Action Check ---
        threshold = config.get("warn_threshold", 0) # Default 0 means disabled
        action = config.get("warn_action", "none").lower()
        action_duration_str = config.get("warn_timeout_duration", "1h")

        if threshold > 0 and warnings_count >= threshold and action != "none":
            auto_reason = f"Automatic action: Reached {warnings_count}/{threshold} warnings. Last warning reason: {reason}"
            print(f"User {member.name} reached warning threshold ({warnings_count}/{threshold}). Triggering action: {action}")

            action_success = False
            action_embed = None
            action_performed_str = "Unknown Action" # For user feedback

            # Ensure bot has permissions for the automatic action
            if action == "timeout" and ctx.guild.me.guild_permissions.moderate_members:
                timeout_duration = parse_duration(action_duration_str)
                if timeout_duration and timeout_duration > datetime.timedelta(0) and timeout_duration <= datetime.timedelta(days=28):
                    try:
                        await member.timeout(timeout_duration, reason=auto_reason)
                        until_ts = int((discord.utils.utcnow() + timeout_duration).timestamp())
                        action_performed_str = f"timed out for {action_duration_str}"
                        action_embed = self._create_mod_log_embed(f"Auto Timeout ({action_duration_str})", member, self.bot.user, auto_reason, color=EMBED_COLORS.get("warning", discord.Color.orange()))
                        action_success = True
                        # Try DMing about auto-action
                        await self._send_dm_notification(member, "Automatic Timeout", ctx.guild.name, auto_reason, self.bot.user, duration=action_duration_str, expires_timestamp=until_ts)
                    except Exception as e:
                        print(f"Auto-timeout failed for {member.name}: {e}")
                        await log_func(ctx.guild, discord.Embed(title="Auto-Mod Error", description=f"Failed to auto-timeout {member.mention}. Error: {e}", color=EMBED_COLORS.get("error", discord.Color.red())), log_type='mod_log')
                else:
                    print(f"Invalid auto-timeout duration configured: {action_duration_str}")
                    await log_func(ctx.guild, discord.Embed(title="Auto-Mod Config Error", description=f"Invalid auto-timeout duration '{action_duration_str}' configured.", color=EMBED_COLORS.get("error", discord.Color.red())), log_type='mod_log')

            elif action == "kick" and ctx.guild.me.guild_permissions.kick_members:
                 try:
                    # Try DMing before kicking
                    await self._send_dm_notification(member, "Automatic Kick", ctx.guild.name, auto_reason, self.bot.user)
                    await member.kick(reason=auto_reason)
                    action_performed_str = "kicked"
                    action_embed = self._create_mod_log_embed("Auto Kick", member, self.bot.user, auto_reason, color=EMBED_COLORS.get("warning", discord.Color.orange()))
                    action_success = True
                 except Exception as e:
                    print(f"Auto-kick failed for {member.name}: {e}")
                    await log_func(ctx.guild, discord.Embed(title="Auto-Mod Error", description=f"Failed to auto-kick {member.mention}. Error: {e}", color=EMBED_COLORS.get("error", discord.Color.red())), log_type='mod_log')

            elif action == "ban" and ctx.guild.me.guild_permissions.ban_members:
                 try:
                     # Try DMing before banning
                    await self._send_dm_notification(member, "Automatic Ban", ctx.guild.name, auto_reason, self.bot.user)
                    await member.ban(reason=auto_reason, delete_message_days=0)
                    action_performed_str = "banned"
                    action_embed = self._create_mod_log_embed("Auto Ban", member, self.bot.user, auto_reason, color=EMBED_COLORS.get("error", discord.Color.red()))
                    action_success = True
                 except Exception as e:
                    print(f"Auto-ban failed for {member.name}: {e}")
                    await log_func(ctx.guild, discord.Embed(title="Auto-Mod Error", description=f"Failed to auto-ban {member.mention}. Error: {e}", color=EMBED_COLORS.get("error", discord.Color.red())), log_type='mod_log')

            # Announce the auto-action in channel if successful
            if action_success and action_embed:
                 await ctx.send(embed=discord.Embed(description=f"🚨 {member.mention} reached {warnings_count} warnings and has been automatically **{action_performed_str}**.", color=action_embed.color))
                 await log_func(ctx.guild, action_embed, log_type='mod_log')


    @commands.command(name='warnings', aliases=['warnlist'], help='Shows warnings for a user.')
    @commands.has_permissions(kick_members=True) # Perm level to view warnings
    @commands.guild_only()
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        """Displays the warning history for a member.
        Usage: z.warnings @User
        """
        config = await get_config(ctx.guild.id)
        user_id_str = str(member.id)
        # Ensure warnings and the user's entry exist and are lists
        user_warnings_data = config.get("warnings", {})
        user_warnings = user_warnings_data.get(user_id_str, []) if isinstance(user_warnings_data, dict) else []

        if not isinstance(user_warnings, list) or not user_warnings:
            await ctx.send(embed=discord.Embed(description=f"✅ {member.mention} has no recorded warnings.", color=EMBED_COLORS.get("success", discord.Color.green())))
            return

        embed = discord.Embed(
            title=f"Warnings for {member.display_name}",
            description=f"Total warnings: {len(user_warnings)}",
            color=EMBED_COLORS.get("info", discord.Color.blue())
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Show latest warnings first. Optionally paginate later.
        max_warnings_display = 10
        # Sort by timestamp (which is also the ID) descending
        display_warnings = sorted(user_warnings, key=lambda w: w.get('timestamp', 0), reverse=True)[:max_warnings_display]

        for i, warn in enumerate(display_warnings):
            mod_id = warn.get('moderator_id')
            mod = ctx.guild.get_member(mod_id) if mod_id else self.bot.user # Assume bot if no mod_id (e.g., future auto-warns?)
            mod_name = mod.mention if mod else f"Unknown ID: {mod_id}"
            timestamp = warn.get('timestamp', 0)
            warning_id = warn.get('id', timestamp) # Use timestamp if no specific ID field
            reason = warn.get('reason', 'No reason recorded.')
            if len(reason) > 150: reason = reason[:147] + "..." # Truncate long reasons for display

            # Format timestamp for display
            time_str = f"<t:{timestamp}:f>" if timestamp else "Unknown time"
            field_name = f"#{len(user_warnings) - i} (ID: `{warning_id}`)" # Count down from total
            field_value = f"**Moderator:** {mod_name}\n**Reason:** {reason}\n**Date:** {time_str}"
            embed.add_field(name=field_name, value=field_value, inline=False)

        if len(user_warnings) > max_warnings_display:
             embed.set_footer(text=f"Showing the latest {max_warnings_display} of {len(user_warnings)} total warnings.")
        else:
             embed.set_footer(text=f"Requested by {ctx.author.display_name}")

        await ctx.send(embed=embed)


    @commands.command(name='clearwarns', aliases=['delwarn', 'rmwarn'], help='Deletes warnings for a user.')
    @commands.has_permissions(manage_guild=True) # Higher permission needed to delete records
    @commands.guild_only()
    async def clearwarns(self, ctx: commands.Context, member: discord.Member, *, warning_ref: str):
        """Deletes a specific warning by ID or all warnings.
        Usage:
        z.clearwarns @User <warning_id>
        z.clearwarns @User all
        """
        config = await get_config(ctx.guild.id)
        log_func = await self._get_log_function()
        user_id_str = str(member.id)

        # Ensure warnings structure is valid before accessing
        warnings_data = config.get("warnings", {})
        if not isinstance(warnings_data, dict):
            await ctx.send(embed=discord.Embed(description="⚠️ Warning data structure is invalid. Cannot clear warnings.", color=EMBED_COLORS.get("error", discord.Color.red())))
            return
        user_warnings = warnings_data.get(user_id_str, [])
        if not isinstance(user_warnings, list) or not user_warnings:
            await ctx.send(embed=discord.Embed(description=f"✅ {member.mention} has no warnings to clear.", color=EMBED_COLORS.get("success", discord.Color.green())))
            return

        cleared_count = 0
        action_desc = ""

        if warning_ref.lower() == "all":
            cleared_count = len(user_warnings)
            if user_id_str in config["warnings"]:
                del config["warnings"][user_id_str] # Remove user entry entirely
            action_desc = f"Cleared **all {cleared_count}** warnings"
        else:
            # Try to interpret as warning ID (integer)
            try:
                target_id = int(warning_ref)
                initial_len = len(user_warnings)
                # Filter out the warning with the matching ID
                new_warnings = [w for w in user_warnings if w.get('id', w.get('timestamp', 0)) != target_id]
                cleared_count = initial_len - len(new_warnings)

                if cleared_count > 0:
                    if not new_warnings: # Remove user entry if list becomes empty
                         if user_id_str in config["warnings"]: del config["warnings"][user_id_str]
                    else:
                        config["warnings"][user_id_str] = new_warnings
                    action_desc = f"Cleared warning with ID `{target_id}`"
                else:
                    # No warning with that ID was found
                    await ctx.send(embed=discord.Embed(description=f"❌ Warning ID `{target_id}` not found for {member.mention}.", color=EMBED_COLORS.get("error", discord.Color.red())))
                    return # Stop if warning not found

            except ValueError:
                # Input wasn't 'all' or a valid integer ID
                await ctx.send(embed=discord.Embed(description=f"❌ Invalid input: `{warning_ref}`. Please provide a numeric warning ID or the word 'all'.", color=EMBED_COLORS.get("error", discord.Color.red())))
                return

        # Save the changes if any warnings were cleared
        if cleared_count > 0:
            await save_config(ctx.guild.id, config)

            # Confirmation and Logging
            confirm_embed = discord.Embed(
                description=f"✅ {action_desc} for {member.mention}.",
                color=EMBED_COLORS.get("success", discord.Color.green())
            )
            confirm_embed.set_footer(text=f"Action by {ctx.author.display_name}")
            await ctx.send(embed=confirm_embed)

            log_embed = discord.Embed(
                title="Warning(s) Cleared",
                description=f"**User:** {member.mention} ({member.id})\n**Moderator:** {ctx.author.mention}\n**Action:** {action_desc}",
                color=EMBED_COLORS.get("success", discord.Color.green()),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"{action_desc} for {member.name} by {ctx.author.name} in {ctx.guild.name}")
        # else: No need to send another message if count was 0 (handled above)


    # --- Warn Config Subcommand Group ---
    @commands.group(name='warnconfig', invoke_without_command=True, help="Configure automatic actions based on warnings.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def warnconfig(self, ctx: commands.Context):
        """Shows the current warning auto-action configuration."""
        config = await get_config(ctx.guild.id)
        threshold = config.get("warn_threshold", 0)
        action = config.get("warn_action", "none")
        duration = config.get("warn_timeout_duration", "1h")

        embed = discord.Embed(title="Warning Auto-Action Config", color=EMBED_COLORS.get("info", discord.Color.blue()), guild=ctx.guild)
        embed.add_field(name="Threshold", value=f"`{threshold}` warnings (0 = disabled)", inline=False)
        embed.add_field(name="Action on Threshold", value=f"`{action}` (Valid: none, timeout, kick, ban)", inline=False)
        if action == "timeout":
             # Validate duration display just in case it was manually edited badly
             parsed_dur = parse_duration(duration)
             valid_dur_str = f"`{duration}`" + (" (Valid)" if parsed_dur else " ⚠️ **(Invalid Format!)**")
             embed.add_field(name="Timeout Duration", value=valid_dur_str, inline=False)
        embed.set_footer(text=f"Use `{ctx.prefix}warnconfig <threshold|action|duration> <value>`")
        await ctx.send(embed=embed)

    @warnconfig.command(name='threshold', help="Sets the warning count to trigger action (0 disables).")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def warnconfig_threshold(self, ctx: commands.Context, count: int):
        """Sets the warning threshold. Usage: z.warnconfig threshold 3"""
        if count < 0:
            await ctx.send(embed=discord.Embed(description="❌ Threshold cannot be negative. Use 0 to disable.", color=EMBED_COLORS.get("error", discord.Color.red())))
            return
        # Optionally set a max threshold? e.g., 20
        # if count > 20:
        #     await ctx.send(embed=discord.Embed(description="❌ Threshold seems too high. Max recommended is 20.", color=EMBED_COLORS.get("warning")))
        #     return

        config = await get_config(ctx.guild.id)
        config["warn_threshold"] = count
        await save_config(ctx.guild.id, config)
        await ctx.send(embed=discord.Embed(description=f"✅ Warning threshold set to **{count}** warnings." + (" (Disabled)" if count == 0 else ""), color=EMBED_COLORS.get("success", discord.Color.green())))

    @warnconfig.command(name='action', help="Sets the action on threshold (none, timeout, kick, ban).")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def warnconfig_action(self, ctx: commands.Context, action_type: str):
        """Sets the automatic warning action. Usage: z.warnconfig action timeout"""
        valid_actions = ["none", "timeout", "kick", "ban"]
        action_type_lower = action_type.lower()
        if action_type_lower not in valid_actions:
             await ctx.send(embed=discord.Embed(description=f"❌ Invalid action type. Use one of: `{'`, `'.join(valid_actions)}`.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return

        config = await get_config(ctx.guild.id)
        config["warn_action"] = action_type_lower
        await save_config(ctx.guild.id, config)
        await ctx.send(embed=discord.Embed(description=f"✅ Warning action set to **`{action_type_lower}`**.", color=EMBED_COLORS.get("success", discord.Color.green())))

    @warnconfig.command(name='duration', help="Sets duration for 'timeout' action (e.g., 1h, 15m).")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def warnconfig_duration(self, ctx: commands.Context, duration_str: str):
        """Sets the timeout duration used by the automatic warning action. Usage: z.warnconfig duration 2h"""
        duration = parse_duration(duration_str)
        if duration is None or duration <= datetime.timedelta(seconds=0):
             await ctx.send(embed=discord.Embed(description=f"❌ Invalid duration format: `{duration_str}`. Use like `10m`, `1h`, `2d` (max 28 days, positive).", color=EMBED_COLORS.get("error", discord.Color.red())))
             return
        # parse_duration already checks max 28 days

        config = await get_config(ctx.guild.id)
        config["warn_timeout_duration"] = duration_str # Store the string representation
        await save_config(ctx.guild.id, config)
        await ctx.send(embed=discord.Embed(description=f"✅ Warning timeout duration set to **`{duration_str}`**.", color=EMBED_COLORS.get("success", discord.Color.green())))


    # --- Message Clearing (Purge) ---
    @commands.command(name='clear', aliases=['purge', 'prune'], help='Deletes messages in the current channel.')
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True) # Bot also needs this perm
    @commands.guild_only()
    async def clear(self, ctx: commands.Context, amount: int, member: discord.Member | None = None):
        """Deletes a specified number of messages, optionally from a specific user.
        Usage:
        z.clear 50
        z.clear 20 @User
        """
        if amount <= 0:
            await ctx.send(embed=discord.Embed(description="❌ Amount must be a positive number.", color=EMBED_COLORS.get("error", discord.Color.red())), delete_after=10)
            try: await ctx.message.delete(delay=1) # Delete command message too
            except: pass
            return

        # Limit amount to avoid excessive API calls or hitting limits quickly.
        # Purge can only delete 100 at a time and messages < 14 days old.
        limit = min(amount, 100) + 1 # Add 1 to potentially include the command message if not deleted first
        log_func = await self._get_log_function()
        deleted_messages = []

        try:
            # Delete the command message itself first (reduces count needed for purge)
            try: await ctx.message.delete()
            except discord.NotFound: pass # Ignore if already gone
            except discord.Forbidden: # Can't delete command msg, proceed with purge anyway
                await ctx.send("⚠️ Could not delete command message (Missing Permissions?). Proceeding with purge.", delete_after=10)

            # Perform the purge
            if member:
                # Purge messages from a specific member
                check = lambda m: m.author == member
                deleted_messages = await ctx.channel.purge(limit=limit-1, check=check, before=ctx.message.created_at, oldest_first=False) # limit-1 because cmd msg deleted
                delete_type = f"from {member.mention}"
            else:
                # Purge any messages
                 deleted_messages = await ctx.channel.purge(limit=limit-1, before=ctx.message.created_at, oldest_first=False)
                 delete_type = "messages"

            deleted_count = len(deleted_messages)

            # Send confirmation message (and delete it after a few seconds)
            confirm_msg_content = f"✅ Deleted **{deleted_count}** {delete_type}."
            confirm_msg = await ctx.send(embed=discord.Embed(description=confirm_msg_content, color=EMBED_COLORS.get("success", discord.Color.green())), delete_after=7)

            # Log the action
            log_embed = discord.Embed(
                 title="Messages Cleared",
                 description=f"**Moderator:** {ctx.author.mention}\n**Channel:** {ctx.channel.mention}\n**Count:** {deleted_count}",
                 color=EMBED_COLORS.get("info", discord.Color.blue()),
                 timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            if member: log_embed.description += f"\n**Target User:** {member.mention}"
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"{ctx.author.name} cleared {deleted_count} messages in #{ctx.channel.name} ({ctx.guild.name}). Target: {'All' if not member else member.name}")

        except discord.Forbidden:
             # This likely means bot lacks Manage Messages in the channel
             await ctx.send(embed=discord.Embed(description="❌ **Error:** I need the 'Manage Messages' permission to delete messages in this channel.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except discord.HTTPException as e:
             # Often happens when trying to delete messages > 14 days old, or other API issues
             await ctx.send(embed=discord.Embed(description=f"❌ An error occurred (possibly trying to delete messages older than 14 days): {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
             print(f"Error during clear command (HTTPException): {e}")
        except Exception as e:
            # Catch other unexpected errors
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during clear: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during clear command: {e}")


    # --- Channel Locking/Unlocking ---

    @commands.command(name='lock', help='Locks the channel (denies @everyone send messages).')
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True) # Needs manage_roles or manage_permissions
    @commands.guild_only()
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, reason: str | None = None):
        """Locks a channel, preventing @everyone from sending messages.
        Defaults to the current channel if none specified.
        Usage: z.lock [#channel] [Optional Reason]
        """
        target_channel = channel or ctx.channel
        reason = reason or "No reason specified"
        overwrite = target_channel.overwrites_for(ctx.guild.default_role)
        log_func = await self._get_log_function()

        # Check if already locked (send_messages is explicitly False)
        if overwrite.send_messages is False:
            await ctx.send(embed=discord.Embed(description=f"⚠️ {target_channel.mention} is already locked.", color=EMBED_COLORS.get("warning", discord.Color.orange())))
            return

        # Apply the lock
        overwrite.send_messages = False
        mod_reason_audit = f"Channel locked by {ctx.author.name}. Reason: {reason}"

        try:
            await target_channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=mod_reason_audit)

            # Send confirmation to context channel
            await ctx.send(embed=discord.Embed(description=f"🔒 {target_channel.mention} has been **locked**.", color=EMBED_COLORS.get("warning", discord.Color.orange())))

            # Attempt to send notification in the locked channel itself (if different)
            if target_channel != ctx.channel:
                 try:
                     await target_channel.send(embed=discord.Embed(title="🔒 Channel Locked", description=f"This channel has been locked by a moderator. Reason: {reason}", color=EMBED_COLORS.get("warning", discord.Color.orange())))
                 except discord.Forbidden:
                     print(f"Could not send lock notification in {target_channel.mention} (Forbidden).")
                 except Exception as e:
                     print(f"Error sending lock notification in {target_channel.mention}: {e}")

            # Log action
            log_embed = discord.Embed(title="Channel Locked", color=EMBED_COLORS.get("warning", discord.Color.orange()), timestamp=datetime.datetime.now(datetime.timezone.utc))
            log_embed.description=f"**Channel:** {target_channel.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"Channel #{target_channel.name} locked by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I need 'Manage Roles' or 'Manage Permissions' permission to lock channels.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during lock: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during lock command for #{target_channel.name}: {e}")


    @commands.command(name='unlock', help='Unlocks a previously locked channel.')
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True) # Needs manage_roles or manage_permissions
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, reason: str | None = None):
        """Unlocks a channel, allowing @everyone to send messages again (restores default perm).
        Defaults to the current channel if none specified.
        Usage: z.unlock [#channel] [Optional Reason]
        """
        target_channel = channel or ctx.channel
        reason = reason or "No reason specified"
        overwrite = target_channel.overwrites_for(ctx.guild.default_role)
        log_func = await self._get_log_function()

        # Check if already unlocked (send_messages is not explicitly False)
        if overwrite.send_messages is not False: # None (inherit) or True means unlocked
            await ctx.send(embed=discord.Embed(description=f"ℹ️ {target_channel.mention} is not currently locked.", color=EMBED_COLORS.get("info", discord.Color.blue())))
            return

        # Apply the unlock: Resetting to None inherits category/server perms.
        overwrite.send_messages = None
        mod_reason_audit = f"Channel unlocked by {ctx.author.name}. Reason: {reason}"

        try:
            await target_channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=mod_reason_audit)

            # Send confirmation to context channel
            await ctx.send(embed=discord.Embed(description=f"🔓 {target_channel.mention} has been **unlocked**.", color=EMBED_COLORS.get("success", discord.Color.green())))

            # Attempt notification in the unlocked channel itself
            if target_channel != ctx.channel:
                 try:
                     await target_channel.send(embed=discord.Embed(title="🔓 Channel Unlocked", description=f"This channel has been unlocked by a moderator.", color=EMBED_COLORS.get("success", discord.Color.green())))
                 except discord.Forbidden: pass # Ignore if bot can't send
                 except Exception as e: print(f"Error sending unlock notification in {target_channel.mention}: {e}")


            # Log action
            log_embed = discord.Embed(title="Channel Unlocked", color=EMBED_COLORS.get("success", discord.Color.green()), timestamp=datetime.datetime.now(datetime.timezone.utc))
            log_embed.description=f"**Channel:** {target_channel.mention}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"Channel #{target_channel.name} unlocked by {ctx.author.name} in {ctx.guild.name}. Reason: {reason}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I need 'Manage Roles' or 'Manage Permissions' permission.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during unlock: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
            print(f"Error during unlock command for #{target_channel.name}: {e}")


    # --- Slowmode Command ---
    @commands.command(name='slowmode', help='Sets slowmode delay for a channel (in seconds).')
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def slowmode(self, ctx: commands.Context, seconds: int, channel: discord.TextChannel | None = None):
        """Sets the slowmode delay for a channel. Use 0 to disable. Max 21600 (6 hours).
        Usage: z.slowmode <seconds> [#channel (optional)]
        """
        target_channel = channel or ctx.channel
        log_func = await self._get_log_function()

        # Validate seconds input
        max_slowmode = 21600 # Discord's limit (6 hours)
        if not 0 <= seconds <= max_slowmode:
             await ctx.send(embed=discord.Embed(description=f"❌ Slowmode delay must be between 0 and {max_slowmode} seconds.", color=EMBED_COLORS.get("error", discord.Color.red())))
             return

        mod_reason_audit = f"Slowmode {'set to ' + str(seconds) + 's' if seconds > 0 else 'disabled'} by {ctx.author.name}."

        try:
            await target_channel.edit(slowmode_delay=seconds, reason=mod_reason_audit)

            if seconds > 0:
                # Format seconds into hours/minutes/seconds if needed
                m, s = divmod(seconds, 60)
                h, m = divmod(m, 60)
                duration_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

                message = f"🐌 Slowmode enabled in {target_channel.mention} with a **{duration_str}** delay."
                color = EMBED_COLORS.get("info", discord.Color.blue())
            else:
                 message = f"✅ Slowmode disabled in {target_channel.mention}."
                 color = EMBED_COLORS.get("success", discord.Color.green())

            # Send confirmation
            await ctx.send(embed=discord.Embed(description=message, color=color))

            # Log action
            log_embed = discord.Embed(title="Slowmode Updated", color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
            log_embed.description=f"**Channel:** {target_channel.mention}\n**Moderator:** {ctx.author.mention}\n**Delay:** {seconds} seconds"
            await log_func(ctx.guild, log_embed, log_type='mod_log')
            print(f"Slowmode in #{target_channel.name} ({ctx.guild.name}) set to {seconds}s by {ctx.author.name}")

        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(description="❌ **Error:** I need the 'Manage Channel' permission to change slowmode.", color=EMBED_COLORS.get("error", discord.Color.red())))
        except Exception as e:
             await ctx.send(embed=discord.Embed(description=f"❗ An unexpected error occurred during slowmode: {e}", color=EMBED_COLORS.get("error", discord.Color.red())))
             print(f"Error during slowmode command for #{target_channel.name}: {e}")


    # --- Cog-Specific Error Handler ---
    # This catches errors occurring in any command within this cog that aren't handled by the command's own try/except blocks
    async def cog_command_error(self, ctx: commands.Context, error):
        """Handles errors specific to the Moderation cog."""
        # Prevent handling errors if the command has its own handler
        if hasattr(ctx.command, 'on_error'):
            return

        # Unwrap CommandInvokeError to get the original exception
        if isinstance(error, commands.CommandInvokeError):
            error = error.original

        # Handle common permission errors first
        if isinstance(error, commands.MissingPermissions):
             perms_needed = ', '.join([f"`{perm.replace('_', ' ').title()}`" for perm in error.missing_permissions])
             await ctx.send(embed=discord.Embed(description=f"🚫 You lack the required permission(s): {perms_needed}.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(error, commands.BotMissingPermissions):
             perms_needed = ', '.join([f"`{perm.replace('_', ' ').title()}`" for perm in error.missing_permissions])
             await ctx.send(embed=discord.Embed(description=f"⚙️ I lack the required permission(s): {perms_needed}.", color=EMBED_COLORS.get("error", discord.Color.red())))
        # Handle common argument errors
        elif isinstance(error, commands.MemberNotFound):
             await ctx.send(embed=discord.Embed(description=f"❌ Member not found: `{error.argument}`. Please mention a valid member or use their ID.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(error, commands.UserNotFound): # For ban/unban/etc. using User converter
             await ctx.send(embed=discord.Embed(description=f"❌ User not found: `{error.argument}`. Please provide a valid User ID or mention.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(error, commands.MissingRequiredArgument):
             param_name = error.param.name
             usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"
             await ctx.send(embed=discord.Embed(description=f"❌ Missing argument: `{param_name}`.\n**Usage:** `{usage}`", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(error, commands.BadArgument) or isinstance(error, commands.BadUnionArgument):
             # Handle general bad arguments or failures in Union converters
             usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"
             await ctx.send(embed=discord.Embed(description=f"❌ Invalid argument provided. Check the format.\n**Usage:** `{usage}`", color=EMBED_COLORS.get("error", discord.Color.red())))
        # Handle context errors
        elif isinstance(error, commands.GuildRequired):
            pass # Silently ignore if used in DMs, main bot check might handle this too
        elif isinstance(error, commands.NoPrivateMessage):
             await ctx.send(embed=discord.Embed(description="<:error:123> This command cannot be used in Direct Messages.", color=EMBED_COLORS.get("error", discord.Color.red())))
        # Handle specific discord API errors if not caught by command
        elif isinstance(error, discord.Forbidden):
             # This might catch cases where specific actions fail inside a command's logic
             await ctx.send(embed=discord.Embed(description=f"❌ **Permission Error:** I lack the necessary permissions to perform this action fully. Please check my role permissions.", color=EMBED_COLORS.get("error", discord.Color.red())))
             print(f"Caught discord.Forbidden in cog_command_error for command {ctx.command.name}: {error}")
        elif isinstance(error, discord.HTTPException):
              await ctx.send(embed=discord.Embed(description=f"❌ An API error occurred: {error.status} {error.code} - {error.text}", color=EMBED_COLORS.get("error", discord.Color.red())))
              print(f"Caught discord.HTTPException in cog_command_error for command {ctx.command.name}: {error}")
        # Fallback for other unexpected errors
        else:
             print(f"Unhandled error in Moderation cog command '{ctx.command.name}': {error.__class__.__name__} - {error}")
             # Send a generic error message
             await ctx.send(embed=discord.Embed(description="❗ An unexpected error occurred while running this command.", color=EMBED_COLORS.get("error", discord.Color.red())))


# --- Setup Function ---
# This function is called by bot.py to load the cog
async def setup(bot: commands.Bot):
    # You might want checks here, e.g., ensure dependent utils loaded okay
    # For now, we assume they are handled or print warnings during import
    await bot.add_cog(Moderation(bot))
    print("Moderation Cog loaded successfully.")