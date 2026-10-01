import discord
from game_logic.error_handling import error_message
from game_logic.calculations import calculate_user_stats, equipments
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
            await ctx.send(embed=error_message(e))
            return

        await ctx.send('You have created an account, you may start your journey!')

    @commands.command(name='delete', help='Delete your user :(')
    async def delete(self, ctx: commands.Context):
        try: 
            await self.db.get_user_info(ctx.author.id)
        except ValueError as e:
            await ctx.send(embed=error_message(e))
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
        try:
            user_info = await self.db.get_user_info(user.id)
        except ValueError as e:
            await ctx.send(embed=error_message(e))
            return
        user_stats = await calculate_user_stats(self.db, user)
        embed = discord.Embed(
            title=f'{user.display_name}\'s Profile!',
            description='',
            color=discord.Color.darker_grey()
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar)
        embed.description += '**Stats**\n'
        for stat, value in user_stats.items():
            embed.description += f'> **{stat.replace("_", " ").capitalize()}: {value}**\n'
            if f'base_{stat}' in user_info:
                del user_info[f'base_{stat}']
        embed.description += '\n'
        
        del user_info['user_id']
        del user_info['max_hp']
        del user_info['max_mana']
        user_info['current_hp'] = user_info.pop('hp')
        user_info['current_mana'] = user_info.pop('mana')
        embed.description += '**Equipment/Info**\n'
        for info, value in user_info.items():
            if value is not None:
                embed.description += f"> **{info.replace('_', ' ').capitalize()}: {self.db.items[value]['name'] if self.db.items.get(value) else value}**\n"

        await ctx.send(embed=embed)

        