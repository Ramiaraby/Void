import discord
from discord.ext import commands

def error_message(error):
    embed = discord.Embed(
        color=discord.Color.red(), description=f'**{error}**', title=':warning: Action Failed'
    )
    embed.set_footer(text="Your action could not be completed.")
    return embed