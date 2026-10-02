import io

import discord
from cogs.utility import Pagination
from game_logic.error_handling import error_message
from game_logic.image_creation import create_profile_image, create_inventory_pages, create_map_image
from discord.ext import commands
from data.database import MainDB

class MapView(discord.ui.View):
    """Arrow buttons under the map image. Each press walks one tile and swaps the picture in the same message."""

    BLOCKED_TEXT = {
        'edge': "That's the edge of the world.",
        'water': "Water is in the way.",
    }

    def __init__(self, db: MainDB, user: discord.User):
        super().__init__(timeout=180)
        self.db = db
        self.user = user
        self.message = None  # set after sending, so the buttons can be disabled on timeout

        # 3x3 pad: arrows in a plus shape, refresh in the middle, the corners are just spacers
        layout = (
            (None, ('⬆️', 0, -1), None),
            (('⬅️', -1, 0), ('🔄', 0, 0), ('➡️', 1, 0)),
            (None, ('⬇️', 0, 1), None),
        )
        for row, cells in enumerate(layout):
            for cell in cells:
                if cell is None:
                    self.add_item(discord.ui.Button(label='\u200b', style=discord.ButtonStyle.secondary, disabled=True, row=row))
                    continue
                emoji, dx, dy = cell
                style = discord.ButtonStyle.secondary if (dx, dy) == (0, 0) else discord.ButtonStyle.primary
                button = discord.ui.Button(emoji=emoji, style=style, row=row)
                button.callback = self._make_callback(dx, dy)
                self.add_item(button)

    def _blocked_text(self, blocked: dict) -> str:
        kind = blocked['type']
        if kind in self.BLOCKED_TEXT:
            return self.BLOCKED_TEXT[kind]
        if kind == 'object':
            name = self.db.objects.get(blocked['id'], {}).get('name', 'Something')
        else:
            name = self.db.mobs.get(blocked['id'], {}).get('name', 'Something')
        return f"{name} is in the way."

    def _make_callback(self, dx: int, dy: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()  # rendering can take a moment, don't let the click time out
            note = ''
            try:
                if (dx, dy) != (0, 0):
                    result = await self.db.move(self.user.id, x=dx or None, y=dy or None)
                    if result['blocked_by'] is not None:
                        note = '\n' + self._blocked_text(result['blocked_by'])
                image, caption = await create_map_image(self.db, self.user)
            except ValueError as e:
                await interaction.followup.send(embed=error_message(e), ephemeral=True)
                return
            await interaction.edit_original_response(
                content=caption + note,
                attachments=[discord.File(io.BytesIO(image), filename='map.png')],
                view=self,
            )
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ This isn't your map. Use !map to see yours.", ephemeral=True)
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

        file = await create_profile_image(self.db, user)
        await ctx.send(file=file)
        

    @commands.command(name='inv', aliases=['inventory'], help='Check your inventory.')
    async def inv(self, ctx: commands.Context):
        try:
            pages, captions = await create_inventory_pages(self.db, ctx.author)
        except ValueError as e:
            await ctx.send(embed=error_message(e))
            return

        if len(pages) == 1:
            # nothing to flip through, so no buttons
            await ctx.send(content=captions[0], file=discord.File(io.BytesIO(pages[0]), filename='inventory.png'))
            return

        view = Pagination(pages, author_id=ctx.author.id, filename='inventory')
        view.message = await ctx.send(**view.send_kwargs(), view=view)

    @commands.command(name='map', help='Look around you on your map and walk with the arrow buttons.')
    async def show_map(self, ctx: commands.Context):
        try:
            if not await self.db.map_exists(ctx.author.id):
                # first time: every player gets their own world (could move to the start command later)
                await self.db.generate_map(ctx.author.id)
            async with ctx.typing():
                image, caption = await create_map_image(self.db, ctx.author)
        except ValueError as e:
            await ctx.send(embed=error_message(e))
            return

        view = MapView(self.db, ctx.author)
        view.message = await ctx.send(content=caption, file=discord.File(io.BytesIO(image), filename='map.png'), view=view)