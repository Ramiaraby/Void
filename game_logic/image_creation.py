from PIL import Image, ImageDraw, ImageFont
import discord
from data.database import MainDB

async def create_profile_image(db: MainDB, author: discord.User):
    user_info = await db.get_user_info(author.id)
    equipment_to_display = {
        'helmet': (22, 25), 
        'chestplate': (22, 125), 
        'leggings': (22, 225), 
        'boots': (22, 325), 
        'weapon': (315, 330), 
        'pickaxe': (315, 25),
        'axe': (315, 125),
        'fishing_rod': (315, 230),
        'accessory': (315, 330)
    }
