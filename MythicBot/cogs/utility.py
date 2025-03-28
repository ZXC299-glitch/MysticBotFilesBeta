# cogs/utility.py
import discord
from discord.ext import commands
import datetime
import time
import platform # For potential system info later, if needed

# Import necessary components from other files in the project
# Ensure these paths/imports match your project structure
try:
    # Assumes bot.py is in the parent directory
    from bot import EMBED_COLORS, BOT_PREFIX
except ImportError:
    # Fallback or default values if bot.py structure differs or for standalone testing
    print("Warning: Could not import EMBED_COLORS or BOT_PREFIX from bot.py. Using defaults.")
    EMBED_COLORS = {
        "default": discord.Color.blue(), "success": discord.Color.green(),
        "error": discord.Color.red(), "warning": discord.Color.orange(),
        "info": discord.Color.blurple(),
    }
    BOT_PREFIX = "z."


class Utility(commands.Cog):
    """Helpful utility commands like user/server info, ping, avatar, and help."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time() # Store bot start time for uptime calculation if needed

    # --- Help Command ---
    # This replaces the default help command (ensure help_command=None in Bot init)
    @commands.command(name='help', help='Displays information about commands.')
    async def help_command(self, ctx: commands.Context, *, command_name: str = None):
        """Shows help for all commands or a specific command.
        Usage:
        z.help
        z.help <command_name>
        """
        prefix = ctx.prefix # Get the prefix used in the command invocation

        if command_name:
            # --- Help for a specific command ---
            command = self.bot.get_command(command_name)

            if command is None or command.hidden:
                await ctx.send(embed=discord.Embed(description=f"❌ Command or group `{command_name}` not found.", color=EMBED_COLORS.get("error", discord.Color.red())))
                return

            embed = discord.Embed(
                title=f"Command: `{prefix}{command.qualified_name}`",
                description=command.help or "No detailed description provided.",
                color=EMBED_COLORS.get("info", discord.Color.blue())
            )

            # Construct Usage field
            usage = f"`{prefix}{command.qualified_name}"
            if command.signature:
                usage += f" {command.signature}`"
            else:
                usage += "`"
            embed.add_field(name="Usage", value=usage, inline=False)

            # Add Aliases if they exist
            if command.aliases:
                alias_str = ", ".join([f"`{a}`" for a in command.aliases])
                embed.add_field(name="Aliases", value=alias_str, inline=False)

            # Add Cooldown info if applicable
            if command.cooldown:
                cooldown = command.cooldown
                embed.add_field(name="Cooldown", value=f"{cooldown.rate} time(s) per {cooldown.per:.0f} seconds", inline=False)

            # Add Required Permissions (Check if checks exist)
            required_perms = []
            if command.checks:
                for check in command.checks:
                    # This is a basic check, more robust parsing might be needed for custom checks
                    if "has_permissions" in str(check): # Simple check based on function name
                        # Attempt to extract permissions from the check if possible (can be complex)
                        # For now, just indicate permissions are needed
                         try:
                             # Permissions are often stored in requires, but this depends on implementation
                             perms = check.__closure__[0].cell_contents.keys() # Fragile inspection
                             required_perms.extend([p.replace('_', ' ').title() for p in perms])
                         except (AttributeError, IndexError, TypeError):
                             required_perms.append("Specific Permissions") # Fallback

            if required_perms:
                 perm_str = ", ".join(sorted(list(set(required_perms)))) # Unique and sorted
                 embed.add_field(name="Required Permissions", value=perm_str, inline=False)

            # Check if command is guild_only
            if command.guild_only:
                 embed.add_field(name="Context", value="Server Only", inline=True)

            await ctx.send(embed=embed)

        else:
            # --- List all commands, grouped by Cog ---
            embed = discord.Embed(
                title=f"{self.bot.user.name} Help",
                description=f"Use `{prefix}help <command_name>` for details on a specific command.",
                color=EMBED_COLORS.get("default", discord.Color.blue())
            )
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)

            # Group commands by cog
            cogs_cmds = {}
            for cog_name, cog in self.bot.cogs.items():
                # Get visible commands from the cog
                cog_commands = [cmd for cmd in cog.get_commands() if not cmd.hidden]
                if cog_commands:
                    # Sort commands alphabetically within the cog
                    cog_commands.sort(key=lambda c: c.name)
                    cogs_cmds[cog_name] = cog_commands

            # Sort cog names for consistent order
            sorted_cog_names = sorted(cogs_cmds.keys())

            for cog_name in sorted_cog_names:
                cog_commands = cogs_cmds[cog_name]
                # Format command list for the embed field value
                command_list_str = []
                processed_parents = set() # Keep track of parent commands already listed

                for cmd in cog_commands:
                    if cmd.parent:
                         # If it's a subcommand and its parent hasn't been listed yet
                        if cmd.parent.name not in processed_parents:
                            # List parent command with its subcommands found in this cog
                            sub_cmds = sorted([sub.name for sub in cmd.parent.commands if sub in cog_commands])
                            command_list_str.append(f"`{cmd.parent.name}` (`{'`, `'.join(sub_cmds)}`)")
                            processed_parents.add(cmd.parent.name)
                    elif cmd.name not in processed_parents:
                        # If it's a top-level command
                        command_list_str.append(f"`{cmd.name}`")

                if command_list_str: # Only add field if cog has visible commands formatted
                    # Join the command names/groups for the field value
                    field_value = " ".join(command_list_str)
                    if len(field_value) > 1024: field_value = field_value[:1020] + "..." # Truncate if too long
                    embed.add_field(
                        name=f"**{cog_name}**",
                        value=field_value,
                        inline=False # Display each cog group on a new line
                    )

            embed.set_footer(text=f"Prefix: {prefix} | Total Commands: {len(self.bot.commands)}")
            await ctx.send(embed=embed)

    # --- User Info Command ---
    @commands.command(name='userinfo', aliases=['ui', 'whois'], help='Shows information about a user.')
    @commands.guild_only() # Most details are guild-specific
    async def userinfo(self, ctx: commands.Context, *, member: discord.Member = None):
        """Displays details about a server member. Defaults to self if no member specified.
        Usage: z.userinfo [@User/UserID (optional)]
        """
        target = member or ctx.author # Default to the command author if no member is provided

        embed = discord.Embed(
            title=f"User Information - {target.display_name}",
            description=f"Details for {target.mention}",
            # Use member's top role color if available and not default, else use info color
            color=target.color if target.color != discord.Color.default() else EMBED_COLORS.get("info", discord.Color.blue()),
            timestamp=datetime.datetime.now(datetime.timezone.utc) # Show current time
        )
        embed.set_thumbnail(url=target.display_avatar.url) # Use display_avatar for server-specific avatar

        # Basic User Info
        embed.add_field(name="Username", value=f"`{target.name}#{target.discriminator}`", inline=True)
        embed.add_field(name="User ID", value=f"`{target.id}`", inline=True)

        # Status (with basic emoji representation - consider using custom server emojis if available)
        status_map = {
            discord.Status.online: "🟢 Online",
            discord.Status.idle: "🟠 Idle",
            discord.Status.dnd: "🔴 Do Not Disturb",
            discord.Status.offline: "⚫ Offline",
            discord.Status.invisible: "⚪ Invisible (Offline)" # Note: Invisible appears Offline
        }
        # Use get() with a default for safety, although all statuses should be covered
        embed.add_field(name="Status", value=status_map.get(target.status, str(target.status).title()), inline=True)

        # Timestamps using Discord's formatting
        created_at_unix = int(target.created_at.timestamp())
        embed.add_field(name="Account Created", value=f"<t:{created_at_unix}:F> (<t:{created_at_unix}:R>)", inline=False)

        if target.joined_at: # joined_at might be None if member info isn't fully cached
            joined_at_unix = int(target.joined_at.timestamp())
            embed.add_field(name="Joined Server", value=f"<t:{joined_at_unix}:F> (<t:{joined_at_unix}:R>)", inline=False)
        else:
             embed.add_field(name="Joined Server", value="*Could not determine join date.*", inline=False)

        # Roles (excluding @everyone, listing highest first)
        roles = [role.mention for role in reversed(target.roles) if role != ctx.guild.default_role]
        role_count = len(roles)
        role_str = ", ".join(roles) if roles else "None"
        # Handle cases where role list is too long for an embed field (1024 chars)
        if len(role_str) > 1024:
             role_str = role_str[:1000] + "... (and more)"
        embed.add_field(name=f"Roles ({role_count})", value=role_str, inline=False)

        # Key Details
        embed.add_field(name="Highest Role", value=target.top_role.mention, inline=True)
        embed.add_field(name="Is Bot?", value="Yes" if target.bot else "No", inline=True)

        # Timeout Status
        if target.timed_out_until:
             timeout_unix = int(target.timed_out_until.timestamp())
             embed.add_field(name="Timed Out Until", value=f"<t:{timeout_unix}:R>", inline=True)

        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # --- Server Info Command ---
    @commands.command(name='serverinfo', aliases=['si', 'guildinfo'], help='Shows information about the server.')
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        """Displays detailed information about the current server."""
        guild = ctx.guild

        embed = discord.Embed(
            title=f"Server Information - {guild.name}",
            color=EMBED_COLORS.get("info", discord.Color.blue()),
            timestamp=guild.created_at # Show server creation time as the main timestamp
        )
        # Set thumbnail to server icon if available
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        # Set image to server banner if available
        if guild.banner:
             embed.set_image(url=guild.banner.with_format('png').url) # Request PNG format

        # Core Server Details
        embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=True)
        # Ensure owner is fetched if not readily available (might be needed in large guilds)
        owner = guild.owner or await guild.fetch_member(guild.owner_id) # Fetch if needed
        embed.add_field(name="Owner", value=owner.mention if owner else "Unknown", inline=True)
        created_at_unix = int(guild.created_at.timestamp())
        embed.add_field(name="Created On", value=f"<t:{created_at_unix}:F> (<t:{created_at_unix}:R>)", inline=True)

        # Member Counts (Fetch members if needed for accurate online count, but can be slow/intensive)
        total_members = guild.member_count # Usually accurate
        # Online count requires member cache or fetching. Let's estimate based on available cache.
        # Note: This might be inaccurate if members intent is off or cache is incomplete.
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        humans = sum(1 for m in guild.members if not m.bot) # Relies on member cache
        bots = total_members - humans if humans is not None else "N/A" # Calculate if possible
        member_counts_str = (
             f"**Total:** {total_members}\n"
             f"**Humans:** {humans}\n"
             f"**Bots:** {bots}\n"
             f"**Online:** {online_members} (approx.)"
        )
        embed.add_field(name="Members", value=member_counts_str, inline=True)

        # Channel Counts
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        stage_channels = len(guild.stage_channels)
        forum_channels = len(guild.forum_channels)
        categories = len(guild.categories)
        total_channels = text_channels + voice_channels + stage_channels + forum_channels
        channel_counts_str = (
            f"**Total:** {total_channels}\n"
            f"**Text:** {text_channels} | **Voice:** {voice_channels}\n"
            f"**Stage:** {stage_channels} | **Forum:** {forum_channels}\n"
            f"**Categories:** {categories}"
        )
        embed.add_field(name="Channels", value=channel_counts_str, inline=True)

        # Other Details
        embed.add_field(name="Verification Level", value=str(guild.verification_level).replace('_', ' ').title(), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Emojis", value=f"{len(guild.emojis)}/{guild.emoji_limit}", inline=True)
        embed.add_field(name="Stickers", value=f"{len(guild.stickers)}/{guild.sticker_limit}", inline=True)

        # Server Features
        if guild.features:
             # Format features nicely
             features_str = ", ".join([f"`{f.replace('_', ' ').title()}`" for f in guild.features])
             if len(features_str) > 1024: features_str = features_str[:1020] + "..."
             embed.add_field(name="Features", value=features_str, inline=False)
        else:
             embed.add_field(name="Features", value="None", inline=False)

        # Boost Status
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0 # Default to 0 if None
        embed.add_field(name="Boost Status", value=f"Level {boost_level} with {boost_count} boosts", inline=False)

        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


    # --- Avatar Command ---
    @commands.command(name='avatar', aliases=['av', 'pfp'], help='Shows a user\'s avatar.')
    async def avatar(self, ctx: commands.Context, *, user: discord.User = None):
        """Displays a user's avatar (server-specific if in server, else global).
        Usage: z.avatar [@User/UserID (optional)]
        """
        target = user or ctx.author # Default to command author if no user specified

        # Get the display avatar (server avatar > global avatar)
        display_avatar = target.display_avatar # This smartly chooses the best one available

        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            # No description needed, image is the focus
            color=EMBED_COLORS.get("info", discord.Color.blue())
        )
        # Request a larger size for better quality, format can be webp (default), png, jpg, jpeg
        embed.set_image(url=display_avatar.replace(size=1024))
        # Add links to different formats/sizes? Optional.
        embed.add_field(name="Links", value=f"[PNG]({display_avatar.replace(format='png', size=1024)}) | [JPG]({display_avatar.replace(format='jpg', size=1024)}) | [WEBP]({display_avatar.replace(format='webp', size=1024)})", inline=False)

        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


    # --- Ping Command ---
    @commands.command(name='ping', help='Checks the bot\'s latency.')
    async def ping(self, ctx: commands.Context):
        """Shows the bot's response time (REST) and websocket heartbeat latency."""
        # 1. Get REST latency (time from command sent to bot response processed)
        start_time = time.monotonic()
        message = await ctx.send(embed=discord.Embed(description="Pinging...", color=EMBED_COLORS.get("info", discord.Color.blue())))
        end_time = time.monotonic()
        latency_rest = (end_time - start_time) * 1000 # In milliseconds

        # 2. Get Websocket latency (heartbeat)
        latency_ws = self.bot.latency * 1000 # Already in seconds, convert to ms

        # 3. Edit the message with results
        embed = discord.Embed(
            title="Pong! 🏓",
            color=EMBED_COLORS.get("success", discord.Color.green()),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Websocket Latency", value=f"`{latency_ws:.2f} ms`", inline=True)
        embed.add_field(name="REST Latency", value=f"`{latency_rest:.2f} ms`", inline=True)

        # Determine overall health based on latency (example thresholds)
        if latency_ws > 1000 or latency_rest > 1500:
             health = "🔴 Poor"
             embed.color = EMBED_COLORS.get("error", discord.Color.red())
        elif latency_ws > 400 or latency_rest > 800:
             health = "🟠 Okay"
             embed.color = EMBED_COLORS.get("warning", discord.Color.orange())
        else:
             health = "🟢 Good"

        embed.add_field(name="Status", value=health, inline=True)

        try:
            await message.edit(embed=embed)
        except discord.NotFound:
             # If the original message was deleted before edit, send a new one
             await ctx.send(embed=embed)


    # --- Role Info Command ---
    @commands.command(name='roleinfo', aliases=['ri'], help='Shows details about a role.')
    @commands.guild_only()
    async def roleinfo(self, ctx: commands.Context, *, role: discord.Role):
        """Displays information about a specific server role.
        Usage: z.roleinfo <@Role/RoleID/Role Name>
        """
        embed = discord.Embed(
            title=f"Role Information - {role.name}",
            description=f"Details for {role.mention}",
            color=role.color if role.color != discord.Color.default() else EMBED_COLORS.get("info", discord.Color.blue()),
            timestamp=role.created_at # Show role creation date as timestamp
        )

        # Basic Info
        embed.add_field(name="Role ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color (Hex)", value=f"`{role.color}`", inline=True)
        # Member count can be intensive on large guilds if not cached well
        embed.add_field(name="Members", value=str(len(role.members)), inline=True)

        # Position & Display
        embed.add_field(name="Position", value=f"{role.position}/{len(ctx.guild.roles)-1}", inline=True) # Position from bottom (0 is @everyone)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True) # Displayed separately in member list

        # Creation Date
        created_at_unix = int(role.created_at.timestamp())
        embed.add_field(name="Created On", value=f"<t:{created_at_unix}:F> (<t:{created_at_unix}:R>)", inline=False)

        # Permissions (List key ones for brevity)
        perms = role.permissions
        key_perms_list = [
            ("Administrator", perms.administrator),
            ("Manage Server", perms.manage_guild),
            ("Manage Roles", perms.manage_roles),
            ("Manage Channels", perms.manage_channels),
            ("Kick Members", perms.kick_members),
            ("Ban Members", perms.ban_members),
            ("Timeout Members", perms.moderate_members),
            ("Manage Messages", perms.manage_messages),
            ("Mention Everyone", perms.mention_everyone),
            ("View Audit Log", perms.view_audit_log),
        ]
        enabled_key_perms = [name for name, enabled in key_perms_list if enabled]

        if perms.administrator: # If admin, all perms are granted
            perms_str = "**Administrator** (Grants all permissions)"
        elif enabled_key_perms:
            perms_str = ", ".join([f"`{p}`" for p in enabled_key_perms])
        else:
            perms_str = "None notable"

        # Handle potential length issues
        if len(perms_str) > 1024: perms_str = perms_str[:1020] + "..."
        embed.add_field(name="Key Permissions", value=perms_str, inline=False)

        # Icon (if role has one)
        if role.icon:
             embed.set_thumbnail(url=role.icon.url)
        elif role.unicode_emoji:
             # If no icon but has emoji, maybe add it?
             embed.add_field(name="Emoji", value=role.unicode_emoji, inline=True)


        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # --- Error Handlers for this Cog ---

    @userinfo.error
    async def userinfo_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
             await ctx.send(embed=discord.Embed(description=f"❌ Member not found: `{error.argument}`.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(error, commands.BadArgument):
             await ctx.send(embed=discord.Embed(description=f"❌ Invalid user provided.", color=EMBED_COLORS.get("error", discord.Color.red())))
        else: # Propagate other errors to general handler if needed
             # print(f"Error in userinfo: {error}")
             pass # Let cog_command_error handle or default behavior

    @roleinfo.error
    async def roleinfo_error(self, ctx: commands.Context, error):
         if isinstance(error, commands.RoleNotFound):
              await ctx.send(embed=discord.Embed(description=f"❌ Role not found: `{error.argument}`. Check spelling, mention, or ID.", color=EMBED_COLORS.get("error", discord.Color.red())))
         elif isinstance(error, commands.MissingRequiredArgument):
              await ctx.send(embed=discord.Embed(description=f"❌ Please specify a role to get info about.", color=EMBED_COLORS.get("error", discord.Color.red())))
         elif isinstance(error, commands.BadArgument):
              await ctx.send(embed=discord.Embed(description=f"❌ Invalid role provided.", color=EMBED_COLORS.get("error", discord.Color.red())))
         else: # Propagate other errors
              # print(f"Error in roleinfo: {error}")
              pass

    async def cog_command_error(self, ctx: commands.Context, error):
        """Handles errors specific to the Utility cog if not caught by command-specific handlers."""
        # Prevent handling errors if the command has its own handler (on_error attribute)
        if hasattr(ctx.command, 'on_error'):
            return

        # Unwrap CommandInvokeError to get the original exception if exists
        original_error = getattr(error, 'original', error)

        # Handle common errors not caught by specific handlers above
        if isinstance(original_error, commands.MissingPermissions):
             perms_needed = ', '.join([f"`{perm.replace('_', ' ').title()}`" for perm in original_error.missing_permissions])
             await ctx.send(embed=discord.Embed(description=f"🚫 You lack the required permission(s): {perms_needed}.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(original_error, commands.BotMissingPermissions):
             perms_needed = ', '.join([f"`{perm.replace('_', ' ').title()}`" for perm in original_error.missing_permissions])
             await ctx.send(embed=discord.Embed(description=f"⚙️ I lack the required permission(s): {perms_needed}.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(original_error, commands.NoPrivateMessage):
             await ctx.send(embed=discord.Embed(description="❌ This command cannot be used in Direct Messages.", color=EMBED_COLORS.get("error", discord.Color.red())))
        elif isinstance(original_error, commands.CommandOnCooldown):
             await ctx.send(embed=discord.Embed(description=f"⏳ This command is on cooldown. Try again in {original_error.retry_after:.2f} seconds.", color=EMBED_COLORS.get("warning", discord.Color.orange())))
        # Add more specific handlers if needed

        # Fallback for unexpected errors
        elif not isinstance(original_error, (commands.CommandNotFound, commands.CheckFailure)): # Ignore CommandNotFound or checks handled elsewhere
             print(f"Unhandled error in Utility cog command '{ctx.command.name}': {original_error.__class__.__name__} - {original_error}")
             # Send a generic error message
             await ctx.send(embed=discord.Embed(description="❗ An unexpected error occurred while running this command.", color=EMBED_COLORS.get("error", discord.Color.red())))


# --- Setup Function ---
# This function is called by bot.py (or main script) to load the cog
async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
    print("Utility Cog loaded successfully.")