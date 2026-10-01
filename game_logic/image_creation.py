from PIL import Image, ImageDraw, ImageFont
import discord
import io
from data.database import MainDB

equipment_to_display = {
    'helmet': (22, 25, 5, 0), # x, y, scale, rotate
    'chestplate': (22, 125, 5, 0), 
    'leggings': (22, 225, 5, 0), 
    'boots': (22, 325, 5, 0), 
    'weapon': (135, -5, 7, -45), 
    'pickaxe': (315, 25, 5, 0),
    'axe': (315, 125, 5, 0),
    'fishing_rod': (315, 230, 5, 0),
    'accessory': (315, 330, 5, 0)
}


async def create_profile_image(db: MainDB, author: discord.User):   
    profile_bg = Image.open('assets/other/profile.png') 
    user_info = await db.get_user_info(author.id)
    for equipment, pos in equipment_to_display.items():
        if user_info[equipment] is not None:
            img = Image.open(
                f'assets/{equipment}/{user_info[equipment]}.png'
            ).convert('RGBA')
            img = img.resize(
                (img.width * pos[2], img.height * pos[2]),
                resample=Image.Resampling.NEAREST
            )
            if pos[3] != 0:
                img = img.rotate(pos[3], expand=True)
            profile_bg.paste(
                img, (pos[0], pos[1]), mask=img    
            )

    buffer = io.BytesIO()
    profile_bg.save(buffer, format="PNG")
    buffer.seek(0)

    return discord.File(buffer, filename="profile.png")





