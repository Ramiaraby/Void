"""
Dev tool: look at a generated map without running the bot.

    python preview_map.py            # random seed
    python preview_map.py 12345      # a specific seed

Writes map_overview.png (whole map, objects as coloured dots) and map_view.png (what !map shows at the
spawn point). Run it from the project root.
"""
import asyncio
import io
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from game_logic import map_generation as mg

ASSETS = Path('assets')

DOT_COLOURS = {
    'oak_tree': (20, 90, 20), 'birch_tree': (60, 140, 40), 'spruce_tree': (10, 60, 40), 'cactus': (30, 120, 60),
    'bush': (90, 170, 60), 'rock': (90, 90, 90), 'coal_ore': (10, 10, 10), 'iron_ore': (200, 140, 100),
    'golden_ore': (255, 215, 0), 'amber_ore': (255, 140, 0), 'ruby_ore': (230, 20, 60),
    'emerald_ore': (0, 220, 100), 'diamond_ore': (0, 230, 255),
}


def load_json(name):
    with open(Path('data') / name, encoding='utf-8') as f:
        return json.load(f)


def build_world(seed: int):
    """Terrain + objects + animals + monsters, the same way MainDB.generate_map(populate=True) does."""
    objects_rules, mobs = load_json('objects.json'), load_json('mobs.json')
    animal_rules = {k: v for k, v in mobs.items() if not v.get('hostile')}
    monster_rules = {k: v for k, v in mobs.items() if v.get('hostile')}
    m = asyncio.run(mg.generate_terrain(seed))
    spawn = m['spawn']
    w, h = m['width'], m['height']
    forbidden = {(spawn[0] + dx, spawn[1] + dy) for dx in range(-1, 2) for dy in range(-1, 2)}
    objects = mg.generate_objects_layer(seed, w, h, m['terrain'], m['biomes'], objects_rules, forbidden)
    blocked = {mg.parse_key(k) for k in objects}
    rng = random.Random(seed)
    animals = mg.generate_entities_layer(rng, w, h, m['terrain'], m['biomes'], animal_rules, {}, blocked, spawn, spawn)
    blocked |= {mg.parse_key(k) for k in animals}
    monsters = mg.generate_entities_layer(rng, w, h, m['terrain'], m['biomes'], monster_rules, {}, blocked, spawn, spawn)
    return m, objects, animals, monsters


def tile_colour(name: str):
    return Image.open(ASSETS / 'map' / f'{name}.png').convert('RGB').getpixel((0, 0))


def render_overview(m, objects, animals, monsters, scale: int = 6) -> Image.Image:
    w, h = m['width'], m['height']
    colours = [tile_colour(name) for name in mg.TILES]
    img = Image.new('RGB', (w * scale, h * scale))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(w):
            draw.rectangle((x * scale, y * scale, (x + 1) * scale - 1, (y + 1) * scale - 1),
                           fill=colours[m['terrain'][y * w + x]])
    pad = max(1, scale // 4)
    for key, object_id in objects.items():
        x, y = mg.parse_key(key)
        draw.rectangle((x * scale + pad, y * scale + pad, (x + 1) * scale - 1 - pad, (y + 1) * scale - 1 - pad),
                       fill=DOT_COLOURS.get(object_id, (255, 0, 255)))
    for key in animals:
        x, y = mg.parse_key(key)
        draw.ellipse((x * scale, y * scale, (x + 1) * scale - 1, (y + 1) * scale - 1), fill=(255, 255, 255), outline=(0, 0, 0))
    for key in monsters:
        x, y = mg.parse_key(key)
        draw.ellipse((x * scale - 1, y * scale - 1, (x + 1) * scale, (y + 1) * scale), fill=(220, 0, 0), outline=(0, 0, 0))
    sx, sy = m['spawn']
    draw.rectangle((sx * scale - 2, sy * scale - 2, (sx + 1) * scale + 1, (sy + 1) * scale + 1), outline=(255, 0, 255), width=2)
    return img


def render_view(m, objects, animals, monsters, center=None) -> Image.Image:
    """The exact picture !map sends, using the real renderer (11x7 tiles around `center`, default the spawn)."""
    from data.database import MainDB
    from game_logic.image_creation import _render_map

    w, h = m['width'], m['height']
    cx, cy = center or m['spawn']
    cols, rows = 11, 7
    x1 = min(max(cx - cols // 2, 0), w - cols)
    y1 = min(max(cy - rows // 2, 0), h - rows)
    state = {'seed': 0, 'width': w, 'height': h, 'position': (cx, cy), 'terrain': m['terrain'], 'biomes': m['biomes'],
             'objects': objects, 'animals': animals, 'monsters': monsters}
    view = MainDB._slice_map(state, x1, y1, x1 + cols - 1, y1 + rows - 1)
    view['player_biome'] = mg.BIOMES[m['biomes'][cy * w + cx]]
    png = _render_map(view, load_json('objects.json'))
    return Image.open(io.BytesIO(png))


if __name__ == '__main__':
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.getrandbits(32)
    world = build_world(seed)
    render_overview(*world).save('map_overview.png')
    render_view(*world).save('map_view.png')
    m, objects, animals, monsters = world
    print(f'seed {seed}: spawn {m["spawn"]}, {len(objects)} objects, {len(animals)} animals, {len(monsters)} monsters')
    print('wrote map_overview.png and map_view.png')
