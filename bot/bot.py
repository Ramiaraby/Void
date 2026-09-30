import discord
from data.database import MainDB
from cogs.utility import UtilityCommands
from cogs.users import UserCommands
from bot.events import Events
from discord.ext import commands

class Bot(commands.Bot):

    def __init__(self, prefix):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=prefix,
            intents=intents,
            help_command=None
        )
        self.db = MainDB()

    async def setup_hook(self):
        await self.add_cog(Events(self))
        await self.add_cog(UtilityCommands(self))
        await self.add_cog(UserCommands(self))