# cogs/verification.py
import discord
from discord.ext import commands
from discord.ui import Button, View
import datetime
from bot import EMBED_COLORS # Import colors from main bot file
from utils.config_manager import get_config, save_config # Import config helpers

# --- Verification Button View ---
class VerificationView(View):
    def __init__(self, member: discord.Member, verified_role_id: int | None, guild_name: str, log_func):
        super().__init__(timeout=None) # Persistent view
        self.member = member
        self.verified_role_id = verified_role_id
        self.guild_name = guild_name
        self.log_func = log_func # Function to call for logging

    @discord.ui.button(label="✅ Verify Me", style=discord.ButtonStyle.success, custom_id="verify_button_persistent")
    async def verify_button_callback(self, interaction: discord.Interaction, button: Button):
        # 1. Check if the interaction user is the intended member
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This verification button is not for you!", ephemeral=True)
            return

        # 2. Check if member is still in the guild (might have left and rejoined)
        guild = interaction.guild
        if not guild: # Should have guild in interaction from DM if bot shares server
             # Attempt to fetch guild if interaction lacks it (less common now)
             guild = self.member.guild
             if not guild:
                 await interaction.response.send_message("Could not determine the server. Please contact an admin.", ephemeral=True)
                 print(f"Error: Guild not found during verification for {self.member.id}")
                 return

        # Refetch member object from guild to ensure it's current
        member = guild.get_member(self.member.id)
        if not member:
            await interaction.response.send_message("It seems you're no longer in the server. Please rejoin and try again.", ephemeral=True)
            button.disabled = True
            await interaction.message.edit(view=self)
            return

        # 3. Assign the role if configured
        feedback_message = f"Verification processed for **{guild.name}**!"
        role_assigned = False
        if self.verified_role_id:
            role = guild.get_role(self.verified_role_id)
            if role:
                if role >= guild.me.top_role:
                     await interaction.response.send_message(
                         f"I cannot assign the '{role.name}' role because it's higher than or equal to my highest role. Please notify an admin.",
                         ephemeral=True
                     )
                     # Log this issue for admins
                     await self.log_func(guild, discord.Embed(
                        title="Verification Error",
                        description=f"Failed to assign verification role to {member.mention}.\nReason: Role '{role.name}' ({role.id}) is too high.",
                        color=EMBED_COLORS["error"]
                     ), log_type='mod_log') # Send to mod log
                     return # Stop processing

                try:
                    await member.add_roles(role, reason="User verified via button click.")
                    feedback_message = f"✅ You have been verified in **{guild.name}** and granted the '{role.name}' role!"
                    role_assigned = True
                    print(f"Assigned role '{role.name}' to {member.name} in {guild.name}")

                    # Log successful verification
                    log_embed = discord.Embed(
                        title="User Verified",
                        description=f"{member.mention} ({member.id}) verified themselves and was assigned the '{role.name}' role.",
                        color=EMBED_COLORS["success"],
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    log_embed.set_author(name=f"{member.name}#{member.discriminator}", icon_url=member.display_avatar.url)
                    await self.log_func(guild, log_embed, log_type='mod_log') # Log to mod log

                except discord.Forbidden:
                    await interaction.response.send_message(
                        f"I lack the 'Manage Roles' permission to assign the verification role in **{guild.name}**. Please contact an admin.",
                        ephemeral=True
                    )
                    # Log this issue
                    await self.log_func(guild, discord.Embed(
                        title="Verification Permission Error",
                        description=f"Failed to assign verification role to {member.mention}.\nReason: Missing 'Manage Roles' permission.",
                        color=EMBED_COLORS["error"]
                     ), log_type='mod_log')
                    return # Stop processing
                except Exception as e:
                    print(f"Error assigning role during verification for {member.name}: {e}")
                    await interaction.response.send_message(
                        "An unexpected error occurred while assigning your role. Please contact an admin.",
                        ephemeral=True
                    )
                    # Log this issue
                    await self.log_func(guild, discord.Embed(
                        title="Verification Error",
                        description=f"Unexpected error assigning role to {member.mention}.\nError: {e}",
                        color=EMBED_COLORS["error"]
                     ), log_type='mod_log')
                    return # Stop processing
            else:
                # Role configured but not found
                feedback_message = f"Verification processed for **{guild.name}**. (Admin Note: Configured verification role ID `{self.verified_role_id}` not found)."
                print(f"Warning: Verified role ID {self.verified_role_id} not found in {guild.name}")
                # Log this issue
                await self.log_func(guild, discord.Embed(
                    title="Verification Config Error",
                    description=f"User {member.mention} clicked verify, but role ID `{self.verified_role_id}` was not found.",
                    color=EMBED_COLORS["warning"]
                 ), log_type='mod_log')
        else:
            # No role configured, just acknowledge the click
            feedback_message = f"✅ Verification button clicked for **{guild.name}**! Welcome!"
             # Log the click even without role assignment
            log_embed = discord.Embed(
                title="User Clicked Verify",
                description=f"{member.mention} ({member.id}) clicked the verification button. No role assignment was configured.",
                color=EMBED_COLORS["info"],
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            log_embed.set_author(name=f"{member.name}#{member.discriminator}", icon_url=member.display_avatar.url)
            await self.log_func(guild, log_embed, log_type='mod_log')


        # 4. Send confirmation to the user (ephemeral)
        try:
            await interaction.response.send_message(feedback_message, ephemeral=True)
        except discord.InteractionResponded: # If logging took too long and we already responded implicitly
             await interaction.followup.send(feedback_message, ephemeral=True)
        except Exception as e:
            print(f"Error sending verification confirmation to {member.name}: {e}")
            # Attempt followup if response failed
            try:
                await interaction.followup.send("Verification processed, but confirmation failed to send directly.", ephemeral=True)
            except: pass # Ignore if followup also fails


        # 5. Disable the button
        button.disabled = True
        button.label = "Verified"
        try:
            await interaction.message.edit(view=self)
        except Exception as e:
            print(f"Error disabling verification button for {member.name}: {e}")
            # Log this failure if needed

        # Optional: Stop the view if you ONLY want one successful verification per message
        # self.stop()


# --- Verification Cog ---
class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Re-add the persistent view on cog load/bot restart
        # Needs the member, role_id, guild_name, and log_func. This is tricky on startup.
        # A better approach for truly persistent views involves storing interaction data
        # and potentially using interaction checks instead of storing member object directly.
        # For simplicity here, we'll rely on on_member_join to send *new* views.
        # If the bot restarts, old buttons might fail if they rely on the specific View instance.
        # Using a persistent view with custom_id="verify_button_persistent" allows *some* recovery
        # if we add an on_interaction listener, but matching the original member/role is hard without a database.

        # A simpler, slightly less robust approach for restarts:
        # We can register the view *class* without instance data on startup.
        # The callback will need to derive context (member, role) from the interaction.
        # This means the member info in the View init might not be usable reliably across restarts.
        # Let's stick to sending a new view on join for this example's scope.


    # Helper to get the logging function from the Logging cog
    async def _get_log_function(self):
        logging_cog = self.bot.get_cog("Logging")
        if logging_cog and hasattr(logging_cog, "log_event"):
            return logging_cog.log_event
        else:
            # Fallback dummy function if Logging cog isn't loaded or ready
            async def dummy_log(*args, **kwargs):
                # print("Debug: Logging cog not available.") # Optional debug print
                pass
            return dummy_log

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Sends verification DM when a new member joins."""
        # Ignore bots
        if member.bot:
            return

        guild = member.guild
        config = await get_config(guild.id)
        verified_role_id = config.get("verified_role")

        # Get the logging function from the Logging cog
        log_event_func = await self._get_log_function()

        print(f'{member.name} (ID: {member.id}) joined {guild.name}. Sending verification DM.')

        embed = discord.Embed(
            title=f"Welcome to {guild.name}!",
            description=(
                f"Hello {member.mention}! 👋\n\n"
                "To gain access to the server, please click the button below.\n\n"
                "*If you have issues, contact a server administrator.*"
            ),
            color=EMBED_COLORS["default"],
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=f"Server ID: {guild.id}")

        # Pass necessary info and the log function to the view
        view = VerificationView(member, verified_role_id, guild.name, log_event_func)

        try:
            await member.send(embed=embed, view=view)
            print(f"Sent verification DM to {member.name}")
        except discord.Forbidden:
            print(f"Could not send verification DM to {member.name} (DMs likely disabled).")
            # Log this failure to the server's log channel if configured
            log_embed = discord.Embed(
                title="Verification DM Failed",
                description=f"Could not send verification DM to {member.mention} ({member.id}). They may have DMs disabled.",
                color=EMBED_COLORS["warning"],
                 timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            log_embed.set_author(name=f"{member.name}#{member.discriminator}", icon_url=member.display_avatar.url)
            await log_event_func(guild, log_embed, log_type='log') # Send to general log
        except Exception as e:
            print(f"An unexpected error occurred sending DM to {member.name}: {e}")


    @commands.command(name='setverifiedrole', help='Sets the role users receive upon verification.')
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def set_verified_role(self, ctx: commands.Context, *, role: discord.Role = None):
        """Sets or clears the role given upon verification.

        Usage:
        z.setverifiedrole @VerifiedRole
        z.setverifiedrole Role Name With Spaces
        z.setverifiedrole none (or leave empty) to clear
        """
        config = await get_config(ctx.guild.id)
        old_role_id = config.get("verified_role")
        old_role = ctx.guild.get_role(old_role_id) if old_role_id else None

        if role is None:
            config["verified_role"] = None
            await save_config(ctx.guild.id, config)
            embed = discord.Embed(
                description="✅ Verification role has been **cleared**.",
                color=EMBED_COLORS["success"]
            )
            if old_role:
                embed.add_field(name="Previous Role", value=old_role.mention, inline=False)
            await ctx.send(embed=embed)
            print(f"Verification role cleared for guild {ctx.guild.id} by {ctx.author.name}")
        else:
             # Check if bot can actually assign this role
            if role >= ctx.guild.me.top_role:
                embed = discord.Embed(
                    description=f"❌ I cannot set {role.mention} as the verification role because it is higher than or equal to my highest role. Please move my role up or choose a lower role.",
                    color=EMBED_COLORS["error"]
                )
                await ctx.send(embed=embed)
                return
            # Check if role is @everyone (cannot be assigned)
            if role == ctx.guild.default_role:
                 embed = discord.Embed(
                    description=f"❌ The {role.mention} role cannot be assigned automatically.",
                    color=EMBED_COLORS["error"]
                )
                 await ctx.send(embed=embed)
                 return


            config["verified_role"] = role.id
            await save_config(ctx.guild.id, config)
            embed = discord.Embed(
                description=f"✅ Verification role set to {role.mention}.",
                color=EMBED_COLORS["success"]
            )
            if old_role and old_role != role:
                 embed.add_field(name="Previous Role", value=old_role.mention, inline=False)
            await ctx.send(embed=embed)
            print(f"Verification role for guild {ctx.guild.id} set to {role.name} ({role.id}) by {ctx.author.name}")

    @set_verified_role.error
    async def set_verified_role_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord.Embed(description="🚫 You need the 'Manage Roles' permission to use this command.", color=EMBED_COLORS["error"]))
        elif isinstance(error, commands.RoleNotFound):
             await ctx.send(embed=discord.Embed(description=f"❌ Role not found: `{error.argument}`. Please provide a valid role name, mention, or ID.", color=EMBED_COLORS["error"]))
        elif isinstance(error, commands.GuildRequired):
            pass # Ignore if used in DMs, handled by global check or cog check
        else:
            print(f"Error in set_verified_role: {error}")
            await ctx.send(embed=discord.Embed(description="❗ An unexpected error occurred.", color=EMBED_COLORS["error"]))


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
    print("Verification Cog loaded.")