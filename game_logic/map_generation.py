import asyncio
import math
import random
import zlib
from collections import deque

# ___________________________
# CONFIG
# ___________________________

# 100x100 = 10,000 tiles: big enough for several distinct biomes and ~40 tiles of walking
# from the centre in any direction, small enough that a whole map is ~10 KB per player.
MAP_WIDTH = 100
MAP_HEIGHT = 100

SAFE_RADIUS = 6        # animals / monsters never appear this close to the player
EDGE_WIDTH = 10        # tiles of coastline noise around the border (the map edge is always ocean)
BRIDGE_MIN_SIZE = 40   # separate landmasses at least this big get joined to the main one by a sandbar

# Biome tuning. Temperature / humidity / elevation are RANKS (0..1 across the whole map), so 0.14 means
# "the coldest 14 % of tiles" whatever the seed. Nudge these to get more/less of a biome.
TUNDRA_BELOW_TEMP = 0.14
DESERT_ABOVE_TEMP = 0.64
DESERT_BELOW_HUMIDITY = 0.50
FOREST_ABOVE_HUMIDITY = 0.62
MOUNTAIN_ABOVE_ELEVATION = 0.84
SNOWY_PEAK_ABOVE_ELEVATION = 0.965  # the highest tops are always snowy...
SNOWY_PEAK_BELOW_TEMP = 0.22        # ...and so are mountains in cold climates
RIVER_FRACTION = 0.07               # share of tiles closest to a river line

# Ground tiles = assets/map/<name>.png.  IDs are what gets stored in the database, so only ever APPEND.
TILES = ('water', 'sand', 'grass', 'snow', 'stone')
WALKABLE_TILES = frozenset({'sand', 'grass', 'snow', 'stone'})

# Biomes decide what spawns where (objects.json / animal.json / monsters.json).  Also append-only.
BIOMES = (
    'ocean', 'beach', 'river', 'plains', 'forest',
    'birch_forest', 'desert', 'tundra', 'mountains', 'snowy_peaks',
)

BIOME_TILE = {
    'ocean': 'water', 'beach': 'sand', 'river': 'water', 'plains': 'grass', 'forest': 'grass',
    'birch_forest': 'grass', 'desert': 'sand', 'tundra': 'snow', 'mountains': 'stone', 'snowy_peaks': 'snow',
}

TILE_ID = {name: i for i, name in enumerate(TILES)}
BIOME_ID = {name: i for i, name in enumerate(BIOMES)}
WALKABLE_IDS = frozenset(TILE_ID[name] for name in WALKABLE_TILES)

# ___________________________
# SMALL HELPERS
# ___________________________


def pack_grid(grid: bytes) -> bytes:
    return zlib.compress(bytes(grid), 9)


def unpack_grid(blob: bytes) -> bytes:
    return zlib.decompress(blob)


def layer_key(x: int, y: int) -> str:
    """Objects / animals / monsters are stored as JSON dicts keyed 'x,y'."""
    return f'{x},{y}'


def parse_key(key: str):
    x, y = key.split(',')
    return int(x), int(y)


# ___________________________
# SEEDED NOISE (pure Python, same result on every machine)
# ___________________________

_MASK64 = (1 << 64) - 1
_GRADIENTS = (
    (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
    (0.7071, 0.7071), (-0.7071, 0.7071), (0.7071, -0.7071), (-0.7071, -0.7071),
)


def _splitmix64(state: int):
    state = (state + 0x9E3779B97F4A7C15) & _MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return state, z ^ (z >> 31)


class _Perlin:
    """2D Perlin noise. Every instance has its own permutation table + offset, derived from (seed, salt)."""

    def __init__(self, seed: int, salt: int):
        state = (seed * 0x2545F4914F6CDD1D + salt * 0x9E3779B97F4A7C15 + 1) & _MASK64
        perm = list(range(256))
        for i in range(255, 0, -1):
            state, z = _splitmix64(state)
            j = z % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        self.perm = perm * 2
        state, z = _splitmix64(state)
        self.offset_x = (z % 10_000) / 7.0
        state, z = _splitmix64(state)
        self.offset_y = (z % 10_000) / 7.0

    def __call__(self, x: float, y: float) -> float:
        """-> roughly [-0.7, 0.7]"""
        p = self.perm
        x += self.offset_x
        y += self.offset_y
        fx = math.floor(x)
        fy = math.floor(y)
        xi = fx & 255
        yi = fy & 255
        x -= fx
        y -= fy
        u = x * x * x * (x * (x * 6 - 15) + 10)
        v = y * y * y * (y * (y * 6 - 15) + 10)

        a = p[xi] + yi
        b = p[xi + 1] + yi
        g00 = _GRADIENTS[p[a] & 7]
        g10 = _GRADIENTS[p[b] & 7]
        g01 = _GRADIENTS[p[a + 1] & 7]
        g11 = _GRADIENTS[p[b + 1] & 7]

        n00 = g00[0] * x + g00[1] * y
        n10 = g10[0] * (x - 1) + g10[1] * y
        n01 = g01[0] * x + g01[1] * (y - 1)
        n11 = g11[0] * (x - 1) + g11[1] * (y - 1)

        nx0 = n00 + u * (n10 - n00)
        nx1 = n01 + u * (n11 - n01)
        return nx0 + v * (nx1 - nx0)


def _fbm(noise: _Perlin, x: float, y: float, octaves: int) -> float:
    """Layered noise, normalised to [0, 1]."""
    total = norm = 0.0
    amplitude = frequency = 1.0
    for _ in range(octaves):
        total += amplitude * noise(x * frequency, y * frequency)
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    value = (total / norm / 0.7071 + 1.0) / 2.0
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _to_ranks(values: list) -> list:
    """Replace each value by its rank in [0, 1]. Noise clumps around 0.5; ranks spread it evenly, so
    'the coldest 20 %' really is 20 % of the map whatever the seed."""
    order = sorted(range(len(values)), key=values.__getitem__)
    last = max(1, len(values) - 1)
    ranks = [0.0] * len(values)
    for position, index in enumerate(order):
        ranks[index] = position / last
    return ranks


# ___________________________
# TERRAIN
# ___________________________

def _label_land(walkable: bytearray, width: int, height: int):
    """Flood-fill the walkable tiles. -> (label per tile or -1, size of each label)."""
    labels = [-1] * (width * height)
    sizes = []
    for start in range(width * height):
        if not walkable[start] or labels[start] != -1:
            continue
        label = len(sizes)
        labels[start] = label
        queue = deque([start])
        count = 0
        while queue:
            i = queue.popleft()
            count += 1
            x, y = i % width, i // width
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    j = ny * width + nx
                    if walkable[j] and labels[j] == -1:
                        labels[j] = label
                        queue.append(j)
        sizes.append(count)
    return labels, sizes


def _join_landmasses(tiles: bytearray, biomes: bytearray, width: int, height: int):
    """A player can't cross water, so: join big separate landmasses to the main one with a sandbar
    (shortest water gap), and drown tiny leftover islands. -> label grid of the final main landmass."""
    sand, water = TILE_ID['sand'], TILE_ID['water']
    beach = BIOME_ID['beach']

    def walkable_grid():
        return bytearray(1 if t in WALKABLE_IDS else 0 for t in tiles)

    for _ in range(16):
        labels, sizes = _label_land(walkable_grid(), width, height)
        if len(sizes) <= 1:
            break
        main = max(range(len(sizes)), key=sizes.__getitem__)
        targets = {c for c, s in enumerate(sizes) if c != main and s >= BRIDGE_MIN_SIZE}
        if not targets:
            break

        # breadth-first search from the main landmass across everything until it touches another one
        parent = [-1] * (width * height)
        seen = bytearray(width * height)
        queue = deque()
        for i, label in enumerate(labels):
            if label == main:
                seen[i] = 1
                queue.append(i)
        reached = -1
        while queue and reached == -1:
            i = queue.popleft()
            x, y = i % width, i // width
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    j = ny * width + nx
                    if not seen[j]:
                        seen[j] = 1
                        parent[j] = i
                        if labels[j] in targets:
                            reached = j
                            break
                        queue.append(j)
        if reached == -1:
            break

        # walk back to the main landmass, turning water on the way into sand
        i = parent[reached]
        while i != -1 and labels[i] != main:
            if tiles[i] == water:
                tiles[i] = sand
                biomes[i] = beach
            i = parent[i]

    labels, sizes = _label_land(walkable_grid(), width, height)
    main = max(range(len(sizes)), key=sizes.__getitem__) if sizes else -1
    for i, label in enumerate(labels):
        if label != -1 and label != main:  # leftover island -> sea
            tiles[i] = water
            biomes[i] = BIOME_ID['ocean']
            labels[i] = -1
    return labels, main


def _pick_spawn(labels: list, main: int, biomes: bytearray, width: int, height: int):
    """Walkable grass closest to the middle of the map (on the main landmass)."""
    cx, cy = (width - 1) / 2, (height - 1) / 2
    friendly = {BIOME_ID['plains'], BIOME_ID['forest'], BIOME_ID['birch_forest']}
    best = fallback = None
    best_d = fallback_d = float('inf')
    for i, label in enumerate(labels):
        if label != main:
            continue
        x, y = i % width, i // width
        d = (x - cx) ** 2 + (y - cy) ** 2
        if biomes[i] in friendly and d < best_d:
            best, best_d = (x, y), d
        if d < fallback_d:
            fallback, fallback_d = (x, y), d
    return best or fallback


def _generate_terrain(seed: int, width: int, height: int) -> dict:
    rng = random.Random(seed)
    size = width * height

    continent = _Perlin(seed, 1)
    hills = _Perlin(seed, 2)
    temperature = _Perlin(seed, 3)
    humidity = _Perlin(seed, 4)
    river_noise = _Perlin(seed, 5)
    variant = _Perlin(seed, 6)
    ford_noise = _Perlin(seed, 7)

    elevation, temp, humid, river, birch = [], [], [], [], []
    for y in range(height):
        for x in range(width):
            elevation.append(0.75 * _fbm(continent, x / 34, y / 34, 4) + 0.25 * _fbm(hills, x / 13, y / 13, 2))
            temp.append(_fbm(temperature, x / 42, y / 42, 3))
            humid.append(_fbm(humidity, x / 38, y / 38, 3))
            river.append(abs(_fbm(river_noise, x / 26, y / 26, 3) - 0.5))
            birch.append(_fbm(variant, x / 11, y / 11, 2))

    elevation = _to_ranks(elevation)
    temp = _to_ranks(temp)
    humid = _to_ranks(humid)
    birch = _to_ranks(birch)
    river_rank = _to_ranks(river)  # low rank = close to the middle of a river line

    sea_level = 0.22 + 0.12 * rng.random()  # a bit different per seed: more lakes, or more land

    tiles = bytearray(size)
    biomes = bytearray(size)
    ocean, beach, river_id = BIOME_ID['ocean'], BIOME_ID['beach'], BIOME_ID['river']
    sand, water = TILE_ID['sand'], TILE_ID['water']

    for y in range(height):
        for x in range(width):
            i = y * width + x

            # the map border is always sea, with a ragged coastline inside it
            edge = min(x, y, width - 1 - x, height - 1 - y)
            falloff = max(0.0, (EDGE_WIDTH - edge) / EDGE_WIDTH) ** 1.5
            e = elevation[i] - 1.1 * falloff
            t = temp[i] - max(0.0, e - 0.6) * 0.35  # colder up high
            h = humid[i]

            if e < sea_level:
                biome = ocean
            elif river_rank[i] < RIVER_FRACTION and e < MOUNTAIN_ABOVE_ELEVATION:
                biome = river_id
            elif e < sea_level + 0.025:
                biome = beach
            elif e >= SNOWY_PEAK_ABOVE_ELEVATION or (e >= MOUNTAIN_ABOVE_ELEVATION and t < SNOWY_PEAK_BELOW_TEMP):
                biome = BIOME_ID['snowy_peaks']
            elif e >= MOUNTAIN_ABOVE_ELEVATION:
                biome = BIOME_ID['mountains']
            elif t < TUNDRA_BELOW_TEMP:
                biome = BIOME_ID['tundra']
            elif t > DESERT_ABOVE_TEMP and h < DESERT_BELOW_HUMIDITY:
                biome = BIOME_ID['desert']
            elif h > FOREST_ABOVE_HUMIDITY:
                biome = BIOME_ID['birch_forest'] if birch[i] > 0.5 else BIOME_ID['forest']
            else:
                biome = BIOME_ID['plains']

            biomes[i] = biome
            tiles[i] = TILE_ID[BIOME_TILE[BIOMES[biome]]]

            # shallow crossings: some stretches of river are sand, so rivers don't wall the map in
            if biome == river_id and _fbm(ford_noise, x / 5, y / 5, 1) > 0.58:
                tiles[i] = sand

    labels, main = _join_landmasses(tiles, biomes, width, height)
    spawn = _pick_spawn(labels, main, biomes, width, height)

    return {
        'seed': seed, 'width': width, 'height': height,
        'terrain': bytes(tiles), 'biomes': bytes(biomes), 'spawn': spawn,
    }


async def generate_terrain(seed: int = None, width: int = MAP_WIDTH, height: int = MAP_HEIGHT) -> dict:
    """
    Seeded, Minecraft-style terrain: elevation (sea / beach / mountains / snowy peaks), temperature and
    humidity (tundra / desert / plains / forest / birch forest), plus rivers with fords and an ocean border.
    Same seed -> same map. Runs in a worker thread so the bot keeps responding.

    -> {'seed', 'width', 'height',
        'terrain': bytes, 'biomes': bytes,   # one byte per tile, index = y * width + x
        'spawn': (x, y)}
    """
    if seed is None:
        seed = random.getrandbits(32)
    return await asyncio.to_thread(_generate_terrain, seed, width, height)


# ___________________________
# OBJECTS / ANIMALS / MONSTERS
# ___________________________

def generate_objects_layer(seed: int, width: int, height: int, terrain: bytes, biomes: bytes,
                           objects: dict, forbidden: set) -> dict:
    """
    Trees, rocks, ores... from objects.json ('biomes' = chance per tile). Deterministic for a seed, so
    calling it again puts every resource back exactly where it started. Trees and ores come in clumps.
    `forbidden` = {(x, y)} tiles to leave free (player, animals, monsters).
    -> {'x,y': object_id}
    """
    rng = random.Random(seed ^ 0x5EED0B1)
    clumps = _Perlin(seed, 8)
    water = TILE_ID['water']

    table = {}  # biome id -> [(cumulative chance, object id)]
    for object_id, data in objects.items():
        for biome_name, chance in data['biomes'].items():
            running = table.setdefault(BIOME_ID[biome_name], [])
            running.append(((running[-1][0] if running else 0.0) + chance, object_id))

    layer = {}
    for y in range(height):
        for x in range(width):
            i = y * width + x
            rules = table.get(biomes[i])
            if not rules or terrain[i] == water or (x, y) in forbidden:
                continue
            clump = 0.35 + 1.3 * _fbm(clumps, x / 6, y / 6, 2)  # ~0.35 (sparse) .. 1.65 (dense)
            roll = rng.random() / clump
            for cumulative, object_id in rules:
                if roll < cumulative:
                    layer[layer_key(x, y)] = object_id
                    break
    return layer


def generate_entities_layer(rng: random.Random, width: int, height: int, terrain: bytes, biomes: bytes,
                            rules: dict, existing: dict, blocked: set, spawn: tuple, player: tuple) -> dict:
    """
    Tops mobs up to the density set in mobs.json ('biomes' = chance per tile, an optional 'min_distance'
    from the map's spawn point, and 'habitat': 'water' for mobs that live on water tiles). Never overwrites anything: existing entities are
    kept and counted, so calling it again just respawns what has been killed.
    `blocked` = {(x, y)} tiles that are taken (objects, other layer, ...).
    -> the new entities only, {'x,y': {'id': ..., 'hp': ...}}
    """
    current = {}
    for entity in existing.values():
        current[entity['id']] = current.get(entity['id'], 0) + 1

    # free tiles per biome id, away from the player; land mobs use walkable tiles, water mobs ('habitat': 'water') water ones
    free_land, free_water = {}, {}
    for y in range(height):
        for x in range(width):
            i = y * width + x
            if (x, y) in blocked or layer_key(x, y) in existing:
                continue
            if math.hypot(x - player[0], y - player[1]) < SAFE_RADIUS:
                continue
            bucket = free_land if terrain[i] in WALKABLE_IDS else free_water
            bucket.setdefault(biomes[i], []).append((x, y))

    added = {}
    for entity_id, data in rules.items():
        free = free_water if data.get('habitat') == 'water' else free_land
        min_distance = data.get('min_distance', 0)
        candidates = {}
        expected = 0.0
        for biome_name, chance in data['biomes'].items():
            tiles = [
                t for t in free.get(BIOME_ID[biome_name], [])
                if math.hypot(t[0] - spawn[0], t[1] - spawn[1]) >= min_distance
            ]
            candidates[biome_name] = tiles
            expected += len(tiles) * chance

        # e.g. an expected 2.4 spawns means 2, plus a 40 % chance of a third
        target = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        missing = target - current.get(entity_id, 0)

        pool = [(t, chance) for biome_name, chance in data['biomes'].items() for t in candidates[biome_name]]
        for _ in range(max(0, missing)):
            if not pool:
                break
            # pick a tile with probability proportional to its biome's chance
            index = _weighted_index(rng, pool)
            tile, _chance = pool[index]
            pool[index] = pool[-1]
            pool.pop()
            added[layer_key(*tile)] = {'id': entity_id, 'hp': data['hp']}
            free[biomes[tile[1] * width + tile[0]]].remove(tile)  # next entity type can't reuse this tile
    return added


def _weighted_index(rng: random.Random, pool: list) -> int:
    """Index into [(tile, chance)] chosen with probability proportional to chance."""
    total = sum(chance for _tile, chance in pool)
    roll = rng.random() * total
    running = 0.0
    for index, (_tile, chance) in enumerate(pool):
        running += chance
        if roll < running:
            return index
    return len(pool) - 1
