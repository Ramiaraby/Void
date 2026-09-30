import discord 
from discord.ext import commands


class Pagination(discord.ui.View):
    def __init__(self, pages: list, current_page: int = 0):
        super().__init__(timeout=60)
        self.pages = pages
        self.current_page = current_page

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == 0:
            self.current_page = len(self.pages) - 1
        else:
            self.current_page -= 1

        if type(self.pages[0]) == discord.Embed:
            embed: discord.Embed = self.pages[self.current_page]
            embed.set_footer(text=f'Page {self.current_page+1}/{len(self.pages)}')
            await interaction.response.edit_message(embed=embed)
        if type(self.pages[0]) == str:
            message = self.pages[self.current_page] + f'\nPage {self.current_page+1}/{len(self.pages)}'
            await interaction.response.edit_message(content=message)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == len(self.pages) - 1:
            self.current_page = 0
        else:
            self.current_page += 1

        if type(self.pages[0]) == discord.Embed:
            embed: discord.Embed = self.pages[self.current_page]
            embed.set_footer(text=f'Page {self.current_page+1}/{len(self.pages)}')
            await interaction.response.edit_message(embed=embed)
        if type(self.pages[0]) == str:
            message = self.pages[self.current_page] + f'\nPage {self.current_page+1}/{len(self.pages)}'
            await interaction.response.edit_message(content=message)

    async def on_timeout(self):
        self.stop()

class HelpSelect(discord.ui.Select):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.commands = {}
        self.embeds = {}

        for _, cog in self.bot.cogs.items():
            if len(cog.get_commands()) == 0:
                continue

            self.commands[cog.qualified_name] = cog.get_commands()


        for cog_name, commands in self.commands.items():
            embed = discord.Embed(
                title=f"{cog_name} Commands",
                color=discord.Color.blue()
            )

            for command in commands:
                parameters = ' '.join([f'<{par}>' for par in command.clean_params.keys()])
                embed.add_field(
                    name=f"!{command.qualified_name} " + parameters,
                    value=command.help or "No description provided.",
                    inline=False
                )

            self.embeds[cog_name] = embed

        super().__init__(
            placeholder="Choose a category",
            options=[
                discord.SelectOption(
                    label=cog_name,
                    value=cog_name,
                    description=f"Commands in {cog_name}"
                )
                for cog_name in self.commands.keys()
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=self.embeds[self.values[0]]
        )

class UtilityCommands(commands.Cog, name='Utility'):
    def __init__(self, bot:commands.Bot):
        self.bot = bot


    @commands.command(help="Preview all categories and commands.")
    async def help(self, ctx: commands.Context):
        view = discord.ui.View()
        select = HelpSelect(self.bot)
        view.add_item(select)
        await ctx.send(embed=next(iter(select.embeds.values())), view=view)

    @commands.command(help='Calculates bot\'s latency')
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title="🏓 Pong!",
            color=discord.Color.green()
        )

        embed.add_field(
            name="WebSocket Latency",
            value=f"`{latency}ms`",
            inline=True
        )

        embed.add_field(
            name="Server",
            value=ctx.guild.name if ctx.guild else "DM",
            inline=True
        )

        embed.add_field(
            name="Shard",
            value=f"`{ctx.guild.shard_id if ctx.guild else 'N/A'}`",
            inline=True
        )

        embed.set_footer(
            text=f"Requested by {ctx.author}"
        )

        await ctx.send(embed=embed)