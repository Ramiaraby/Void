import discord
from game_logic import error_handling, image_creation
from discord.ext import commands
from data.database import MainDB

class DeleteView(discord.ui.View):
    def __init__(self, db:MainDB, ctx: commands.Context):
        super().__init__(timeout=60)
        self.db = db
        self.ctx = ctx

    @discord.ui.button(
        label='Confirm', style=discord.ButtonStyle.green, emoji='✅'
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.Button):
        await self.db.delete_user(self.ctx.author.id)
        await interaction.response.send_message('User has been deleted.', ephemeral=True)
        await interaction.message.delete()
        self.stop()

    @discord.ui.button(
        label='Cancel', style=discord.ButtonStyle.red, emoji='❎'
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.Button):
        await interaction.response.send_message('Deletion canceled', ephemeral=True)
        await interaction.message.delete()
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "❌ This confirmation isn't for you.",
                ephemeral=True
            )
            return False

        return True

    async def on_timeout(self):
        self.stop()

class UserCommands(commands.Cog, name='Users'):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: MainDB = self.bot.db

    @commands.command(name='start', help='Start your journey, create a user!')
    async def start(self, ctx: commands.Context):
        try:
            await self.db.add_new_user(ctx.author.id)
        except ValueError as e:
            await ctx.send(embed=error_handling.error_message(e))
            return

        await ctx.send('You have created an account, you may start your journey!')

    @commands.command(name='delete', help='Delete your user :(')
    async def delete(self, ctx: commands.Context):
        try: 
            await self.db.get_user_info(ctx.author.id)
        except ValueError as e:
            await ctx.send(embed=error_handling.error_message(e))
            return

        embed = discord.Embed(
            title=':wastebasket: Delete Your Account',
            description='Are you sure you want to delete your account?',
            colour=discord.Color.red()
        )
        embed.set_footer(text='This cannot be reversed')

        await ctx.send(embed=embed, view=DeleteView(self.db, ctx))

    @commands.command(name='profile', help='Check a user or your own RPG profile.')
    async def profile(self, ctx, user: discord.User=None):
        user = ctx.author if user is None else user

        await ctx.send(file=await image_creation.create_profile_image(self.db, user))