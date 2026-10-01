import asyncio
import io
import re
from pathlib import Path
 
import discord
from PIL import Image, ImageDraw, ImageFont
 
from game_logic.calculations import calculate_user_stats
from data.database import MainDB
 
# ___________________________
# CONFIG
# ___________________________
 
ASSETS = Path(__file__).resolve().parent.parent / 'assets'
TEMPLATE = ASSETS / 'other' / 'profile_sample.png'
FONT_PATH = ASSETS / 'other' / 'pixelfont.TTF'
COIN_PATH = ASSETS / 'other' / 'coin.png'
GEM_PATH = ASSETS / 'other' / 'gem.png'  # optional: drop a 16x16 gem icon here to replace the built-in one
 
# colours picked from the template
TEXT = (255, 255, 255)
TEXT_DARK = (82, 60, 38)
BAR_BORDER = (82, 60, 38)
BAR_BG = (151, 106, 62)
BAR_FILL = (237, 211, 135)
BONUS = (140, 235, 100)    # stat is higher than base thanks to gear
PENALTY = (245, 105, 90)   # stat is lower than base thanks to gear
LINE = (151, 106, 62)      # same colour as the template's dividers
 
equipment_to_display = {
    'helmet': (22, 25, 5, 0),  # x, y, scale, rotate
    'chestplate': (22, 125, 5, 0),
    'leggings': (22, 225, 5, 0),
    'boots': (22, 325, 5, 0),
    'weapon': (135, -5, 7, -45),
    'pickaxe': (315, 25, 5, 0),
    'axe': (315, 125, 5, 0),
    'fishing_rod': (315, 230, 5, 0),
    'accessory': (315, 330, 5, 0),
}
 
# right panel of the template (inside the border)
PANEL_LEFT, PANEL_RIGHT = 424, 734
PANEL_W = PANEL_RIGHT - PANEL_LEFT
 
# centre area of the template (x 120-300, y 120-420): one stat per row
# (stat key, label shown, base value key in user_info or None)
STAT_ROWS = (
    ('strength', 'STR', 'base_strength'),
    ('defense', 'DEF', 'base_defense'),
    ('agility', 'AGI', 'base_agility'),
    ('luck', 'LCK', 'base_luck'),
    ('intelligence', 'INT', 'base_intelligence'),
    ('mining_strength', 'MINE', None),
    ('fishing_power', 'FISH', None),
)
CENTRE_LEFT, CENTRE_RIGHT = 136, 286
 
HP_FILL = (214, 80, 62)
MANA_FILL = (84, 150, 220)
 
GEM_BITMAP = (
    "..########..",
    ".#aabbbbcc#.",
    "#aabbbbbbcc#",
    "############",
    ".#ddbbbbcc#.",
    "..#dbbbcc#..",
    "...#dbbc#...",
    "....#dc#....",
    ".....##.....",
)
GEM_COLOURS = {
    '#': (30, 90, 115, 255), 'a': (215, 255, 255, 255), 'b': (110, 225, 245, 255),
    'c': (60, 175, 215, 255), 'd': (45, 140, 190, 255),
}
 
_font_cache = {}
 
 
def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(str(FONT_PATH), size)
    return _font_cache[size]
 
 
def _fmt(n: int) -> str:
    """The font has no comma or dot, so group digits with spaces (1 534 200) and use 123M / 12B when huge."""
    n = int(n)
    if n < 10 ** 8:
        return f'{n:,}'.replace(',', '  ')
    for suffix, size in (('B', 10 ** 9), ('M', 10 ** 6)):
        if n >= size:
            return f'{n // size}{suffix}'
    return str(n)
 
 
def _clean_name(*candidates: str) -> str:
    """The font only has A-Z, a-z, 0-9 and space - anything else would draw as a box."""
    for name in candidates:
        cleaned = re.sub(r'[^A-Za-z0-9 ]', '', name or '').strip()
        if cleaned:
            return cleaned
    return 'PLAYER'
 
 
def _fit_text(draw, text: str, max_width: int, start_size: int, min_size: int = 20):
    """Shrink the font until the text fits (but stay readable); if it still doesn't, cut it.
    No '..' suffix - the font has no dot glyph."""
    for size in range(start_size, min_size - 1, -1):
        if draw.textlength(text, font=_font(size)) <= max_width:
            return text, _font(size)
    font = _font(min_size)
    while len(text) > 1 and draw.textlength(text, font=font) > max_width:
        text = text[:-1]
    return text.rstrip(), font
 
 
def _load_sprite(path: Path, scale: int) -> Image.Image:
    img = Image.open(path).convert('RGBA')
    return img.resize((img.width * scale, img.height * scale), resample=Image.Resampling.NEAREST)
 
 
def _gem_sprite() -> Image.Image:
    if GEM_PATH.is_file():
        return Image.open(GEM_PATH).convert('RGBA')
    img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    for y, row in enumerate(GEM_BITMAP):
        for x, ch in enumerate(row):
            if ch in GEM_COLOURS:
                img.putpixel((x + 2, y + 3), GEM_COLOURS[ch])
    return img
 
 
# ___________________________
# DRAWING
# ___________________________
 
def _draw_equipment(canvas: Image.Image, user_info: dict):
    for equipment, (x, y, scale, rotate) in equipment_to_display.items():
        item_id = user_info.get(equipment)
        if item_id is None:
            continue
        img = _load_sprite(ASSETS / equipment / f'{item_id}.png', scale)
        if rotate:
            img = img.rotate(rotate, expand=True)
        canvas.paste(img, (x, y), mask=img)
 
 
def _draw_slash(draw, cx: int, cy: int, colour):
    """Pixel-art '/' (the font has none)."""
    for i in range(-9, 10, 3):
        draw.rectangle((cx - i // 3 * 2 - 1, cy + i - 1, cx - i // 3 * 2 + 2, cy + i + 1), fill=colour)
 
 
def _draw_fraction(draw, right_x: int, cy: int, current: int, maximum: int, font):
    max_text, cur_text = _fmt(maximum), _fmt(current)
    max_w = draw.textlength(max_text, font=font)
    slash_cx = int(right_x - max_w - 16)
    draw.text((right_x, cy), max_text, font=font, fill=TEXT, anchor='rm')
    _draw_slash(draw, slash_cx, cy, TEXT)
    draw.text((slash_cx - 16, cy), cur_text, font=font, fill=TEXT, anchor='rm')
 
 
def _draw_header(draw, user_info: dict, name: str):
    cy = 48
    level_text = f"LV {user_info['level']}"
    level_font = _font(24)
    draw.text((PANEL_RIGHT, cy), level_text, font=level_font, fill=TEXT, anchor='rm')
 
    room = PANEL_W - int(draw.textlength(level_text, font=level_font)) - 24
    name, font = _fit_text(draw, name, max_width=room, start_size=28)
    draw.text((PANEL_LEFT, cy), name, font=font, fill=TEXT_DARK, anchor='lm')
 
 
def _draw_currency(canvas, draw, user_info: dict):
    y = 110  # vertical centre of the row
    half = PANEL_W // 2
 
    coin = _load_sprite(COIN_PATH, 2)
    canvas.paste(coin, (PANEL_LEFT, y - coin.height // 2), mask=coin)
    draw.text((PANEL_LEFT + 40, y), _fmt(user_info['coins']), font=_font(23), fill=TEXT, anchor='lm')
 
    gem = _gem_sprite()
    gem = gem.resize((gem.width * 2, gem.height * 2), resample=Image.Resampling.NEAREST)
    canvas.paste(gem, (PANEL_LEFT + half, y - gem.height // 2), mask=gem)
    draw.text((PANEL_LEFT + half + 40, y), _fmt(user_info['gems']), font=_font(23), fill=TEXT, anchor='lm')
 
 
def _draw_bar(draw, label: str, top: int, current: int, maximum: int, fill):
    """Label + 'current / max' on one line, progress bar underneath."""
    label_y = top
    draw.text((PANEL_LEFT, label_y), label, font=_font(22), fill=TEXT, anchor='lm')
    _draw_fraction(draw, PANEL_RIGHT, label_y, current, maximum, _font(22))
 
    bar_top, height, border = top + 18, 22, 4
    draw.rectangle((PANEL_LEFT, bar_top, PANEL_RIGHT, bar_top + height), fill=BAR_BORDER)
    inner = (PANEL_LEFT + border, bar_top + border, PANEL_RIGHT - border, bar_top + height - border)
    draw.rectangle(inner, fill=BAR_BG)
 
    ratio = max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0.0
    fill_w = int((inner[2] - inner[0] + 1) * ratio)
    if fill_w > 0:
        draw.rectangle((inner[0], inner[1], inner[0] + fill_w - 1, inner[3]), fill=fill)
 
 
def _draw_stats(draw, user_info: dict, stats: dict):
    row_h = 38
    first_y = 120 + (300 - len(STAT_ROWS) * row_h) // 2 + row_h // 2
    for row, (key, label, base_key) in enumerate(STAT_ROWS):
        y = first_y + row * row_h
        total = stats[key]
        base = user_info[base_key] if base_key else 0
 
        colour = TEXT
        if total > base:
            colour = BONUS
        elif total < base:
            colour = PENALTY
            
        draw.text((CENTRE_LEFT, y), label, font=_font(23), fill=TEXT, anchor='lm')
        draw.text((CENTRE_RIGHT, y), str(total), font=_font(23), fill=colour, anchor='rm')
 
 
def _render(user_info: dict, stats: dict, name: str, required_exp: int) -> io.BytesIO:
    canvas = Image.open(TEMPLATE).convert('RGBA')
    _draw_equipment(canvas, user_info)
 
    draw = ImageDraw.Draw(canvas)
    _draw_header(draw, user_info, name)
    _draw_currency(canvas, draw, user_info)
 
    # dividers between the right panel's sections
    draw.rectangle((PANEL_LEFT - 6, 76, PANEL_RIGHT + 6, 81), fill=LINE)
    draw.rectangle((PANEL_LEFT - 6, 138, PANEL_RIGHT + 6, 143), fill=LINE)
 
    _draw_bar(draw, 'EXP', 170, user_info['exp'], required_exp, BAR_FILL)
    _draw_bar(draw, 'HP', 258, user_info['hp'], stats['hp'], HP_FILL)
    _draw_bar(draw, 'MANA', 346, user_info['mana'], stats['mana'], MANA_FILL)
 
    _draw_stats(draw, user_info, stats)
 
    buffer = io.BytesIO()
    canvas.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer
 
 
async def create_profile_image(db: MainDB, user: discord.User):
    user_info = await db.get_user_info(user.id)
    stats = await calculate_user_stats(db, user)
    required_exp = db.exp_for_next_level(user_info['level'])
    name = _clean_name(user.display_name, user.name)
 
    # Pillow work is CPU-bound; keep it off the event loop so the bot stays responsive
    buffer = await asyncio.to_thread(_render, user_info, stats, name, required_exp)
    return discord.File(buffer, filename='profile.png')
