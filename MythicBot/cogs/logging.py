# cogs/logging.py
import discord
from discord.ext import commands
import datetime
from bot import EMBED_COLORS
from utils.config_manager import get_config, save_config

class Logging(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def log_event(self, guild: discord.Guild, embed: discord.Embed, log_type: str = 'log'):
        """Logs an embed to the appropriate channel based on log_type."""
        if not guild: return # Need guild context

        config = await get_config(guild.id)
        channel_id = None

        if log_type == 'log': # General logs (joins, leaves, verification failures)
            channel_id = config.get("log_channel")
        elif log_type == 'mod_log': # Moderation actions
            channel_id = config.get("mod_log_channel")
            # Fallback to general log channel if mod_log isn't set
            if not channel_id:
                 channel_id = config.get("log_channel")
        # Add more types if needed (e.g., 'message_log')

        if channel_id:
            log_channel = guild.get_channel(channel_id)
            if log_channel and log_channel.permissions_for(guild.me).send_messages and log_channel.permissions_for(guild.me).embed_links:
                try:
                    await log_channel.send(embed=embed)
                except discord.Forbidden:
                    print(f"Error: Missing permissions to send log message in channel {channel_id} in guild {guild.id}")
                except Exception as e:
                    print(f"Error sending log message to {channel_id} in guild {guild.id}: {e}")
            elif log_channel:
                 print(f"Warning: Cannot send to log channel {channel_id} in {guild.name} due to missing Send/Embed permissions.")
            # else: # Channel ID configured but not found (or inaccessible)
            #    print(f"Warning: Configured log channel {channel_id} not found or inaccessible in {guild.name}.")


    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handles join logging and welcome messages."""
        # Handled by Verification cog for sending DM
        # This part handles channel logging/messages

        if member.bot: # Option: log bot joins separately or ignore
             # return
             pass

        guild = member.guild
        config = await get_config(guild.id)

        # --- Join Log ---
        log_channel_id = config.get("log_channel")
        if log_channel_id:
            log_embed = discord.Embed(
                description=f"{member.mention} **joined the server**",
                color=EMBED_COLORS["success"],
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            log_embed.set_author(name=f"{member.name}#{member.discriminator} (ID: {member.id})", icon_url=member.display_avatar.url)
            # Add account creation date to help spot new accounts
            created_at_unix = int(member.created_at.timestamp())
            log_embed.add_field(name="Account Created", value=f"<t:{created_at_unix}:R> (<t:{created_at_unix}:F>)", inline=False)
            log_embed.set_footer(text=f"Total members: {guild.member_count}")

            await self.log_event(guild, log_embed, log_type='log')


        # --- Welcome Message ---
        welcome_channel_id = config.get("welcome_channel")
        welcome_message = config.get("welcome_message", "Welcome {user.mention} to {server.name}!") # Default value
        if welcome_channel_id and welcome_message:
            welcome_channel = guild.get_channel(welcome_channel_id)
            if welcome_channel and welcome_channel.permissions_for(guild.me).send_messages:
                # Replace placeholders
                formatted_message = welcome_message.format(
                    user=member,
                    server=guild,
                    user_mention=member.mention,
                    user_name=member.name,
                    user_id=member.id,
                    server_name=guild.name,
                    member_count=guild.member_count
                )
                try:
                    await welcome_channel.send(formatted_message, allowed_mentions=discord.AllowedMentions(users=True))
                except discord.Forbidden:
                     print(f"Error: Missing permissions to send welcome message in channel {welcome_channel_id} in guild {guild.id}")
                except Exception as e:
                    print(f"Error sending welcome message to {welcome_channel_id} in guild {guild.id}: {e}")


    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handles leave logging and goodbye messages."""
        if member.bot: # Option: log bot leaves separately or ignore
            # return
            pass

        guild = member.guild
        config = await get_config(guild.id)

        # --- Leave Log ---
        log_channel_id = config.get("log_channel")
        if log_channel_id:
            log_embed = discord.Embed(
                description=f"{member.mention} **left the server**",
                color=EMBED_COLORS["warning"], # Use warning or error color for leaves
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            log_embed.set_author(name=f"{member.name}#{member.discriminator} (ID: {member.id})", icon_url=member.display_avatar.url)
             # Show roles they had (optional, requires member cache or fetching roles just before they left)
            role_list = [r.mention for r in member.roles if r != guild.default_role]
            if role_list:
                # Truncate if too long
                roles_str = ", ".join(role_list)
                if len(roles_str) > 1000:
                    roles_str = roles_str[:1000] + "..."
                log_embed.add_field(name="Roles", value=roles_str or "None", inline=False)

            log_embed.set_footer(text=f"Total members: {guild.member_count}")

            await self.log_event(guild, log_embed, log_type='log')

        # --- Goodbye Message ---
        leave_channel_id = config.get("leave_channel")
        leave_message = config.get("leave_message", "{user.name} has left {server.name}.") # Default value
        if leave_channel_id and leave_message:
            leave_channel = guild.get_channel(leave_channel_id)
            if leave_channel and leave_channel.permissions_for(guild.me).send_messages:
                 # Replace placeholders (member object might have limited data after leave, but name/id are usually safe)
                formatted_message = leave_message.format(
                    user=member,
                    server=guild,
                    user_mention=member.mention, # Might sometimes fail if user data is gone
                    user_name=member.name,
                    user_id=member.id,
                    server_name=guild.name,
                    member_count=guild.member_count
                )
                try:
                    # Avoid pinging users who left
                    await leave_channel.send(formatted_message, allowed_mentions=discord.AllowedMentions.none())
                except discord.Forbidden:
                     print(f"Error: Missing permissions to send leave message in channel {leave_channel_id} in guild {guild.id}")
                except Exception as e:
                    print(f"Error sending leave message to {leave_channel_id} in guild {guild.id}: {e}")

    # --- Configuration Commands ---

    @commands.group(name='setchannel', invoke_without_command=True, help="Configure channels for logging, welcomes, etc.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context):
        """Base command for setting channels. Shows current settings if no subcommand is used."""
        config = await get_config(ctx.guild.id)
        log_ch = ctx.guild.get_channel(config.get("log_channel"))
        mod_log_ch = ctx.guild.get_channel(config.get("mod_log_channel"))
        welcome_ch = ctx.guild.get_channel(config.get("welcome_channel"))
        leave_ch = ctx.guild.get_channel(config.get("leave_channel"))

        embed = discord.Embed(title="Channel Configuration", color=EMBED_COLORS["info"], guild=ctx.guild)
        embed.add_field(name="General Log", value=log_ch.mention if log_ch else "Not Set", inline=False)
        embed.add_field(name="Moderation Log", value=mod_log_ch.mention if mod_log_ch else "Not Set (uses General Log if available)", inline=False)
        embed.add_field(name="Welcome Channel", value=welcome_ch.mention if welcome_ch else "Not Set", inline=False)
        embed.add_field(name="Leave Channel", value=leave_ch.mention if leave_ch else "Not Set", inline=False)
        embed.set_footer(text=f"Use `{ctx.prefix}setchannel <type> #channel` to set.")
        await ctx.send(embed=embed)

    async def _set_channel_helper(self, ctx: commands.Context, channel_type: str, channel: discord.TextChannel | None):
        """Helper function to set a specific channel type."""
        config = await get_config(ctx.guild.id)
        key_name = f"{channel_type}_channel"
        friendly_name = channel_type.replace('_', ' ').title()

        if channel:
            # Check bot permissions in the target channel
            if not channel.permissions_for(ctx.guild.me).send_messages or not channel.permissions_for(ctx.guild.me).embed_links:
                 await ctx.send(embed=discord.Embed(description=f"⚠️ I need 'Send Messages' and 'Embed Links' permissions in {channel.mention} to use it effectively.", color=EMBED_COLORS["warning"]))
                 # Proceed to set it anyway, but warn the user

            config[key_name] = channel.id
            await save_config(ctx.guild.id, config)
            await ctx.send(embed=discord.Embed(description=f"✅ {friendly_name} channel set to {channel.mention}.", color=EMBED_COLORS["success"]))
            print(f"{friendly_name} channel for guild {ctx.guild.id} set to {channel.id} by {ctx.author.name}")
        else:
            # Clear the channel setting
            config[key_name] = None
            await save_config(ctx.guild.id, config)
            await ctx.send(embed=discord.Embed(description=f"✅ {friendly_name} channel has been **cleared**.", color=EMBED_COLORS["success"]))
            print(f"{friendly_name} channel for guild {ctx.guild.id} cleared by {ctx.author.name}")


    @setchannel.command(name='log', help="Sets the channel for general logs (joins, leaves, etc.)")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel_log(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Sets or clears the general log channel. Usage: z.setchannel log #channel | z.setchannel log none"""
        await self._set_channel_helper(ctx, "log", channel)

    @setchannel.command(name='modlog', help="Sets the channel for moderation action logs.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel_modlog(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Sets or clears the moderation log channel. Usage: z.setchannel modlog #channel | z.setchannel modlog none"""
        await self._set_channel_helper(ctx, "mod_log", channel)

    @setchannel.command(name='welcome', help="Sets the channel for welcome messages.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel_welcome(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Sets or clears the welcome message channel. Usage: z.setchannel welcome #channel | z.setchannel welcome none"""
        await self._set_channel_helper(ctx, "welcome", channel)

    @setchannel.command(name='leave', help="Sets the channel for leave messages.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel_leave(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Sets or clears the leave message channel. Usage: z.setchannel leave #channel | z.setchannel leave none"""
        await self._set_channel_helper(ctx, "leave", channel)


    @commands.group(name='setmessage', invoke_without_command=True, help="Configure welcome/leave messages.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setmessage(self, ctx: commands.Context):
        """Base command for setting messages. Shows current settings."""
        config = await get_config(ctx.guild.id)
        welcome_msg = config.get("welcome_message", "Not Set")
        leave_msg = config.get("leave_message", "Not Set")

        embed = discord.Embed(title="Message Configuration", color=EMBED_COLORS["info"], guild=ctx.guild)
        embed.add_field(name="Welcome Message", value=f"```{discord.utils.escape_markdown(welcome_msg)}```" if welcome_msg != "Not Set" else "Not Set", inline=False)
        embed.add_field(name="Leave Message", value=f"```{discord.utils.escape_markdown(leave_msg)}```" if leave_msg != "Not Set" else "Not Set", inline=False)
        embed.add_field(name="Placeholders", value="`{user}` (full name), `{user.mention}`, `{user.name}`, `{user.id}`, `{server.name}`, `{member_count}`", inline=False)
        embed.set_footer(text=f"Use `{ctx.prefix}setmessage <welcome|leave> <your message>`.")
        await ctx.send(embed=embed)

    async def _set_message_helper(self, ctx: commands.Context, message_type: str, *, message: str | None):
        config = await get_config(ctx.guild.id)
        key_name = f"{message_type}_message"
        friendly_name = message_type.title()

        if message and message.lower() not in ['none', 'clear', 'reset']:
             # Limit message length? e.g., max 1000 chars
            max_len = 1500
            if len(message) > max_len:
                await ctx.send(embed=discord.Embed(description=f"❌ {friendly_name} message is too long (max {max_len} characters).", color=EMBED_COLORS["error"]))
                return

            config[key_name] = message
            await save_config(ctx.guild.id, config)
            embed = discord.Embed(title=f"{friendly_name} Message Set", color=EMBED_COLORS["success"])
            embed.description = f"```{discord.utils.escape_markdown(message)}```"
            await ctx.send(embed=embed)
            print(f"{friendly_name} message for guild {ctx.guild.id} set by {ctx.author.name}")
        else:
            # Clear the message (set back to default or None)
            default_welcome = "Welcome {user.mention} to {server.name}!"
            default_leave = "{user.name} has left {server.name}."
            default_msg = default_welcome if message_type == "welcome" else default_leave

            config[key_name] = default_msg # Reset to default
            await save_config(ctx.guild.id, config)
            embed = discord.Embed(description=f"✅ {friendly_name} message has been reset to default.", color=EMBED_COLORS["success"])
            embed.add_field(name="Default", value=f"```{discord.utils.escape_markdown(default_msg)}```")

            await ctx.send(embed=embed)
            print(f"{friendly_name} message for guild {ctx.guild.id} reset by {ctx.author.name}")

    @setmessage.command(name='welcome', help="Sets the welcome message.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setmessage_welcome(self, ctx: commands.Context, *, message: str | None = None):
        """Sets the welcome message. Use placeholders like {user.mention}. Use 'none' to reset.
        Example: z.setmessage welcome Welcome {user.mention} to {server.name}! Enjoy your stay!
        """
        await self._set_message_helper(ctx, "welcome", message)

    @setmessage.command(name='leave', help="Sets the leave message.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setmessage_leave(self, ctx: commands.Context, *, message: str | None = None):
        """Sets the leave message. Use placeholders like {user.name}. Use 'none' to reset.
        Example: z.setmessage leave Goodbye {user.name}, we'll miss you!
        """
        await self._set_message_helper(ctx, "leave", message)


    # Error handler for channel/message setting commands
    async def cog_command_error(self, ctx: commands.Context, error):
        # Handle errors specific to this cog's configuration commands
        if isinstance(error, commands.MissingPermissions):
             await ctx.send(embed=discord.Embed(description=f"🚫 You need the '{error.missing_permissions[0].replace('_',' ').title()}' permission.", color=EMBED_COLORS["error"]))
        elif isinstance(error, commands.ChannelNotFound):
             await ctx.send(embed=discord.Embed(description=f"❌ Channel not found: `{error.argument}`.", color=EMBED_COLORS["error"]))
        elif isinstance(error, commands.BadArgument):
             await ctx.send(embed=discord.Embed(description=f"❌ Invalid argument. Please provide a valid channel mention/ID or message.", color=EMBED_COLORS["error"]))
        elif isinstance(error, commands.GuildRequired):
            pass # Ignore if used in DMs
        else:
             # Re-raise other errors to be caught by global handler or default behavior
             # print(f"Error in Logging cog command: {error}") # Optional debug print
             pass # Let the main bot error handler deal with it


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))
    print("Logging Cog loaded.")