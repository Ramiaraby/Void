import discord

equipments = [
    'helmet', 'chestplate', 'leggings', 'boots', 'weapon', 'pickaxe', 'axe', 'fishing_rod', 'accessory'
]

async def calculate_user_stats(db, user:discord.User):
    user_info = await db.get_user_info(user.id)
    stats = {
        'strength': user_info['base_strength'],
        'agility': user_info['base_agility'],
        'defense': user_info['base_defense'],
        'luck': user_info['base_luck'],
        'intelligence': user_info['base_intelligence'],
        'hp': user_info['max_hp'],
        'mana': user_info['max_mana'],
        'mining_strength': 0,
        'fishing_power': 0,
    }
    for eq in equipments:
        if user_info.get(eq) is not None:
            for modifier, value in db.items[user_info[eq]]['modifiers'].items():
                stats[modifier] += value

    return stats

