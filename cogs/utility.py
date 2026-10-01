import io

import discord
from discord.ext import commands


class Pagination(discord.ui.View):
    """
    Back / Next buttons over a list of pages. A page can be:
      - discord.Embed
      - str
      - image bytes (or io.BytesIO / discord.File, which are read once and kept as bytes)

    For image pages, `captions` (optional, one str per page) is shown as the message text.
    Send the first page with:  view.message = await ctx.send(**view.send_kwargs(), view=view)
    """

    def __init__(self, pages: list, current_page: int = 0, captions: list = None,
                 author_id: int = None, filename: str = 'page'):
        super().__init__(timeout=60)
        self.pages = [self._normalize(page) for page in pages]
        self.current_page = current_page
        self.captions = captions
        self.author_id = author_id  # if set, only this user can press the buttons
        self.filename = filename
        self.message = None  # set after sending, so the buttons can be disabled on timeout

    @staticmethod
    def _normalize(page):
        """discord.File / BytesIO can only be sent once, so keep file pages as plain bytes."""
        if isinstance(page, discord.File):
            data = page.fp.read()
            page.fp.seek(0)
            return data
        if isinstance(page, io.BytesIO):
            return page.getvalue()
        return page

    def _payload(self) -> dict:
        page = self.pages[self.current_page]
        footer = f'Page {self.current_page + 1}/{len(self.pages)}'

        if isinstance(page, discord.Embed):
            page.set_footer(text=footer)
            return {'embed': page}

        if isinstance(page, str):
            return {'content': f'{page}\n{footer}'}

        caption = self.captions[self.current_page] if self.captions else ''
        return {
            'content': f'{caption}\n{footer}'.strip(),
            'file': discord.File(io.BytesIO(page), filename=f'{self.filename}_{self.current_page + 1}.png'),
        }

    def send_kwargs(self) -> dict:
        """Keyword arguments for ctx.send() / channel.send() for the current page."""
        return self._payload()

    async def _show_page(self, interaction: discord.Interaction):
        payload = self._payload()
        if 'file' in payload:
            # editing a message replaces its attachments, so swap the old image for the new one
            payload['attachments'] = [payload.pop('file')]
        await interaction.response.edit_message(**payload, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page - 1) % len(self.pages)
        await self._show_page(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page + 1) % len(self.pages)
        await self._show_page(interaction)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ These buttons aren't for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
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