import discord
from data.database import MainDB
from discord.ext import commands

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db: MainDB = self.bot.db

    @commands.Cog.listener()
    async def on_ready(self):
        await self.db.create_tables()
        print('Bot is online')
