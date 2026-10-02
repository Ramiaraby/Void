import aiosqlite
import json
import random
from game_logic.calculations import calculate_user_stats
from game_logic import map_generation as mapgen
import asyncio

class MainDB:
    def __init__(self):
        self.connection: aiosqlite.Connection | None = None
        self.transaction_lock = asyncio.Lock()
        with open('data/items.json', 'r', encoding='utf-8') as file:
            self.items = json.load(file)
        with open('data/objects.json', 'r', encoding='utf-8') as file:
            self.objects = json.load(file)
        with open('data/mobs.json', 'r', encoding='utf-8') as file:
            self.mobs = json.load(file)

    EQUIPABLE_ITEM_TYPES = frozenset({
        'helmet', 'chestplate', 'leggings', 'boots', 'accessory', 'weapon', 'fishing_rod', 'pickaxe', 'axe'
    })

    # ___________________________
    # DATABASE CONNECTION 
    #____________________________

    async def connect(self):
        if self.connection is None:
            self.connection = await aiosqlite.connect("data/main.db")
            await self.connection.execute("PRAGMA foreign_keys = ON;")

    async def close(self):
        if self.connection is not None:
            await self.connection.close()
            self.connection = None


    # _______________________________
    # TABLE CREATION AND MANAGEMENT
    #________________________________

    async def create_tables(self):
        await self.connect()
        await self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS shop (
                listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id TEXT,
                quantity INTEGER DEFAULT 1 CHECK (quantity > 0),
                price INTEGER CHECK (price > 0)
            );

            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER,
                item_id TEXT,
                quantity INTEGER DEFAULT 1 CHECK (quantity > 0),
                PRIMARY KEY (user_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,

                level INTEGER DEFAULT 1 CHECK (level >= 1),
                exp INTEGER DEFAULT 0 CHECK (exp >= 0),

                hp INTEGER DEFAULT 100,
                max_hp INTEGER DEFAULT 100,
                mana INTEGER DEFAULT 20,
                max_mana INTEGER DEFAULT 20,

                base_strength INTEGER DEFAULT 20,
                base_luck INTEGER DEFAULT 20,
                base_agility INTEGER DEFAULT 20,
                base_defense INTEGER DEFAULT 20,
                base_intelligence INTEGER DEFAULT 20,

                coins INTEGER DEFAULT 0 CHECK (coins >= 0),
                gems INTEGER DEFAULT 20 CHECK (gems >= 0),

                helmet TEXT DEFAULT NULL,
                chestplate TEXT DEFAULT NULL,
                leggings TEXT DEFAULT NULL,
                boots TEXT DEFAULT NULL,
                accessory TEXT DEFAULT NULL,
                weapon TEXT DEFAULT NULL,
                pickaxe TEXT DEFAULT NULL,
                axe TEXT DEFAULT NULL,
                fishing_rod TEXT DEFAULT NULL,

                location_x INTEGER DEFAULT 0,
                location_y INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS maps (
                user_id INTEGER PRIMARY KEY,
                seed INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                spawn_x INTEGER NOT NULL,
                spawn_y INTEGER NOT NULL,
                terrain BLOB NOT NULL,
                biomes BLOB NOT NULL,
                objects TEXT NOT NULL DEFAULT '{}',
                animals TEXT NOT NULL DEFAULT '{}',
                monsters TEXT NOT NULL DEFAULT '{}'
            );
        """)
        await self.connection.commit()

    # ___________________________
    # ITEM MANAGEMENT     
    #____________________________

    async def unequip_item(self, user_id, type: str):
        async with self.transaction_lock:
            try:
                user_info = await self.get_user_info(user_id)

                if type not in self.EQUIPABLE_ITEM_TYPES:
                    raise ValueError('Invalid armor type.')

                if user_info[type] is None:
                    raise ValueError(f'No {type} is currently equipped.')

                equipped_item = user_info[type]

                await self.connection.execute(
                    f"""
                    UPDATE users
                    SET {type} = NULL
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self._add_item(
                    user_id,
                    equipped_item,
                    1
                )
                user_stats = await calculate_user_stats(self, user_info)
                if user_stats['hp'] < user_info['hp']:
                    await self.connection.execute(
                        """
                        UPDATE users
                        SET hp = ?
                        WHERE user_id = ?
                        """,
                        (user_stats['hp'], user_id)
                    )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def equip_item(self, user_id, item_id):
        async with self.transaction_lock:
            try:
                user_info = await self.get_user_info(user_id)

                if item_id not in self.items:
                    raise ValueError("Item does not exist.")

                if await self.search_inventory(user_id, item_id) == 0:
                    raise ValueError("Item not found in inventory.")

                item_type = self.items[item_id]["type"]

                if item_type not in self.EQUIPABLE_ITEM_TYPES:
                    raise ValueError("Item cannot be equipped.")

                cursor = await self.connection.execute(
                    f"""
                    SELECT {item_type}
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                row = await cursor.fetchone()

                equipped_item = None if row is None else row[0]

                if equipped_item == item_id:
                    raise ValueError("Item already equipped.")

                await self.connection.execute(
                    f"""
                    UPDATE users
                    SET {item_type} = ?
                    WHERE user_id = ?
                    """,
                    (item_id, user_id)
                )

                if equipped_item is not None:
                    await self._add_item(
                        user_id,
                        equipped_item,
                        1
                    )

                await self._remove_item(
                    user_id,
                    item_id,
                    1
                )
                
                user_stats = await calculate_user_stats(self, user_info)
                if user_stats['hp'] < user_info['hp']:
                    await self.connection.execute(
                        """
                        UPDATE users
                        SET hp = ?
                        WHERE user_id = ?
                        """,
                        (user_stats['hp'], user_id)
                    )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise
    
    async def add_item(self, user_id, item_id, quantity):
        async with self.transaction_lock:
            try:
                if not isinstance(quantity, int) or quantity <= 0:
                    raise ValueError("Quantity must be greater than 0.")

                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

                if item_id not in self.items:
                    raise ValueError("Item does not exist.")

                await self._add_item(user_id, item_id, quantity)

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise
    async def remove_item(self, user_id, item_id, quantity):
        async with self.transaction_lock:
            try:
                if not isinstance(quantity, int) or quantity <= 0:
                    raise ValueError("Quantity must be greater than 0.")

                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

                if item_id not in self.items:
                    raise ValueError("Item does not exist.")

                await self._remove_item(user_id, item_id, quantity)

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def _add_item(self, user_id, item_id, quantity):
        await self.connection.execute(
            """
            INSERT INTO inventory (user_id, item_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, item_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (user_id, item_id, quantity)
        )
    async def _remove_item(self, user_id, item_id, quantity):
        current_quantity = await self.search_inventory(user_id, item_id)

        if current_quantity == 0:
            raise ValueError("Item not found in inventory.")

        if quantity > current_quantity:
            raise ValueError("Not enough items.")

        if quantity == current_quantity:
            await self.connection.execute(
                """
                DELETE FROM inventory
                WHERE user_id = ? AND item_id = ?
                """,
                (user_id, item_id)
            )
        else:
            await self.connection.execute(
                """
                UPDATE inventory
                SET quantity = quantity - ?
                WHERE user_id = ? AND item_id = ?
                """,
                (quantity, user_id, item_id)
        )

    # ___________________________
    # USER MANAGEMENT
    #____________________________
    
    async def add_new_user(self, user_id):
        async with self.transaction_lock:
            try:
                if await self.user_exists(user_id):
                    raise ValueError('User already exists!')
                await self.connection.execute(
                    """
                    INSERT OR IGNORE INTO users (user_id)
                    VALUES (?)
                    """,
                    (user_id,)
                )

                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise

    async def delete_user(self, user_id):
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError('User was not found.')

                await self.connection.execute(
                    """
                    DELETE FROM inventory
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.execute(
                    """
                    DELETE FROM shop
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.execute(
                    """
                    DELETE FROM maps
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.execute(
                    """
                    DELETE FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def get_user_info(self, user_id):
        if not await self.user_exists(user_id):
            raise ValueError("User not found.")
        cursor = await self.connection.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        row = await cursor.fetchone()
        columns = [column[0] for column in cursor.description]

        return dict(zip(columns, row))

    async def search_inventory(self, user_id, item_id=None):
        if not await self.user_exists(user_id):
            raise ValueError("User not found.")
        if item_id is None:
            cursor = await self.connection.execute(
                """
                SELECT item_id, quantity
                FROM inventory
                WHERE user_id = ?
                """,
                (user_id,)
            )

            inventory = await cursor.fetchall()
            return inventory
        else:
            if item_id not in self.items:
                raise ValueError("Item does not exist.")
                
            cursor = await self.connection.execute(
                """
                SELECT quantity
                FROM inventory
                WHERE user_id = ? AND item_id = ?
                """,
                (user_id, item_id)
            )
    
            result = await cursor.fetchone()
    
            if result is None:
                return 0
    
            return result[0]

    async def user_exists(self, user_id):
        cursor = await self.connection.execute(
            """
            SELECT 1
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        return result is not None

    async def update_user(self, user_id, stat:str, new_value):
        async with self.transaction_lock:
            try:
                user_info = await self.get_user_info(user_id)
                if stat not in user_info or stat == 'user_id':
                    raise ValueError('Invalid user statistic.')

                await self.connection.execute(
                    f"""
                    UPDATE users
                    SET {stat} = ?
                    WHERE user_id = ?
                    """,
                    (new_value, user_id)
                )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise

    # ___________________________
    # LEVELING SYSTEM
    #____________________________

    def exp_for_next_level(self, level: int):
        return int(100 * (1.45 ** (level - 1)))
    
    async def add_exp(self, user_id, amount:int):
        async with self.transaction_lock:
            try:
                if not isinstance(amount, int) or amount <= 0:
                    raise ValueError('EXP amount must be greater than 0.')
                user_info = await self.get_user_info(user_id)

                lvl = user_info['level']
                exp = user_info['exp']+amount
                required_exp = self.exp_for_next_level(lvl)
                
                while exp >= required_exp:
                    exp -= required_exp
                    lvl += 1
                    required_exp = self.exp_for_next_level(lvl)

                await self.connection.execute(
                    """
                    UPDATE users
                    SET exp = ?, level = ?
                    WHERE user_id = ?
                    """,
                    (exp, lvl, user_id)
                )

                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise

    # ___________________________
    # SHOP AND LISTINGS     
    #____________________________

    async def add_listing(self, user_id, item_id, price, quantity=1):
        async with self.transaction_lock:
            try:
                if item_id not in self.items:
                    raise ValueError('Invalid Item.')

                if not isinstance(quantity, int) or quantity <= 0:
                    raise ValueError('Quantity must be greater than 0.')

                if not isinstance(price, int) or price <= 0:
                    raise ValueError('Price must be greater than 0.')

                user_item_quantity = await self.search_inventory(user_id, item_id)

                if user_item_quantity == 0:
                    raise ValueError('Item not found in inventory.')

                if user_item_quantity < quantity:
                    raise ValueError(
                        f'You only have {user_item_quantity} '
                        f'{self.items[item_id]["name"]} in your inventory.'
                    )
                await self._remove_item(
                    user_id,
                    item_id,
                    quantity
                )

                await self.connection.execute(
                    """
                    INSERT INTO shop (user_id, item_id, quantity, price)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, item_id, quantity, price)
                )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def cancel_listing(self, listing_id):
        async with self.transaction_lock:
            listing = await self.search_shop(listing_id)

            if listing is None:
                raise ValueError('Listing was not found.')
            try:
                await self._add_item(
                    listing["user_id"],
                    listing["item_id"],
                    listing["quantity"]
                )

                await self.connection.execute(
                    """
                    DELETE FROM shop
                    WHERE listing_id = ?
                    """,
                    (listing_id,)
                )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def buy_listing(self, user_id, listing_id, quantity='all'):
        async with self.transaction_lock:
            try:
                buying_user_info = await self.get_user_info(user_id)
                listing = await self.search_shop(listing_id)

                if listing is None:
                    raise ValueError('Listing was not found.')

                item_id = listing['item_id']
                selling_user_id = listing['user_id']
                item_shop_quantity = listing['quantity']
                price = listing['price']
                buying_user_coin = buying_user_info['coins']

                if quantity == 'all':
                    quantity = item_shop_quantity

                if not isinstance(quantity, int):
                    raise ValueError('Invalid Quantity.')

                if quantity <= 0:
                    raise ValueError('Quantity must be greater than 0.')

                if user_id == selling_user_id:
                    raise ValueError('Unable to buy from your own shop.')

                if quantity > item_shop_quantity:
                    raise ValueError(
                        f'Only {item_shop_quantity} '
                        f'{self.items[item_id]["name"]} are available.'
                    )

                total_price = price * quantity

                if buying_user_coin < total_price:
                    raise ValueError('Insufficient coins amount.')

                await self._add_item(
                    user_id,
                    item_id,
                    quantity
                )

                await self.connection.execute(
                    """
                    UPDATE users
                    SET coins = coins - ?
                    WHERE user_id = ?
                    """,
                    (total_price, user_id)
                )

                await self.connection.execute(
                    """
                    UPDATE users
                    SET coins = coins + ?
                    WHERE user_id = ?
                    """,
                    (total_price, selling_user_id)
                )

                if quantity == item_shop_quantity:
                    await self.connection.execute(
                        """
                        DELETE FROM shop
                        WHERE listing_id = ?
                        """,
                        (listing_id,)
                    )
                else:
                    await self.connection.execute(
                        """
                        UPDATE shop
                        SET quantity = quantity - ?
                        WHERE listing_id = ?
                        """,
                        (quantity, listing_id)
                    )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise
            
    async def search_shop(
        self,
        listing_id=None,
        item_id=None,
        user_id=None,
        min_price=None,
        max_price=None,
        sort='price_low',
        limit=50
    ):
        valid_sorts = {
            'price_low',
            'price_high',
            'quantity',
            'newest'
        }

        if sort not in valid_sorts:
            raise ValueError('Invalid sort option.')

        if limit <= 0:
            raise ValueError('Limit must be greater than 0.')

        query = """
            SELECT listing_id, user_id, item_id, quantity, price
            FROM shop
            WHERE 1=1
        """

        params = []

        if listing_id is not None:
            query += " AND listing_id = ?"
            params.append(listing_id)

        if item_id is not None:
            query += " AND item_id = ?"
            params.append(item_id)

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        if min_price is not None:
            query += " AND price >= ?"
            params.append(min_price)

        if max_price is not None:
            query += " AND price <= ?"
            params.append(max_price)

        if sort == 'price_low':
            query += " ORDER BY price ASC"
        elif sort == 'price_high':
            query += " ORDER BY price DESC"
        elif sort == 'quantity':
            query += " ORDER BY quantity DESC"
        elif sort == 'newest':
            query += " ORDER BY listing_id DESC"

        query += " LIMIT ?"
        params.append(limit)

        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()

        if listing_id is not None:
            if not rows:
                return None

            row = rows[0]

            return {
                'listing_id': row[0],
                'user_id': row[1],
                'item_id': row[2],
                'quantity': row[3],
                'price': row[4]
            }

        return {
            row[0]: {
                'user_id': row[1],
                'item_id': row[2],
                'quantity': row[3],
                'price': row[4]
            }
            for row in rows
        }

    async def edit_listing(self, listing_id, user_id, price=None, quantity=None):
        async with self.transaction_lock:
            if price is None and quantity is None:
                raise ValueError(
                    'Enter either a price or quantity you want to change.'
                )

            listing = await self.search_shop(listing_id=listing_id)

            if listing is None:
                raise ValueError('Listing was not found.')

            if user_id != listing['user_id']:
                raise ValueError('Only owner of this listing can edit it.')

            if price is not None:
                if not isinstance(price, int) or price <= 0:
                    raise ValueError('Price must be greater than 0.')

            if quantity is not None:
                if not isinstance(quantity, int) or quantity <= 0:
                    raise ValueError('Quantity must be greater than 0.')
            try:
                if quantity is not None:
                    current_quantity = listing['quantity']

                    if quantity > current_quantity:
                        additional_quantity = quantity - current_quantity

                        user_item_quantity = await self.search_inventory(
                            user_id,
                            listing['item_id']
                        )

                        if user_item_quantity < additional_quantity:
                            raise ValueError(
                                f'You only have {user_item_quantity} '
                                f'{self.items[listing["item_id"]]["name"]} '
                                f'in your inventory.'
                            )

                        await self._remove_item(
                            user_id,
                            listing['item_id'],
                            additional_quantity
                        )

                    elif quantity < current_quantity:
                        returned_quantity = current_quantity - quantity

                        await self._add_item(
                            user_id,
                            listing['item_id'],
                            returned_quantity
                        )

                    await self.connection.execute(
                        """
                        UPDATE shop
                        SET quantity = ?
                        WHERE listing_id = ?
                        """,
                        (quantity, listing_id)
                    )

                if price is not None:
                    await self.connection.execute(
                        """
                        UPDATE shop
                        SET price = ?
                        WHERE listing_id = ?
                        """,
                        (price, listing_id)
                    )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise


    # ______________________________________________________________________________
    # MAP SYSTEM  (everything about maps lives down here)
    #
    # Table `maps`, one row per user_id:
    #   seed, width, height, spawn_x, spawn_y
    #   terrain / biomes : compressed grids, 1 byte per tile (see game_logic/map_generation.py)
    #   objects / animals / monsters : JSON dicts keyed "x,y"
    # The player's position is users.location_x / users.location_y.
    # _______________________________________________________________________________

    MAX_MOVE_STEPS = 20  # most tiles a single move() may walk

    async def map_exists(self, user_id):
        cursor = await self.connection.execute(
            """
            SELECT 1
            FROM maps
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        return result is not None

    async def _get_map(self, user_id):
        """The whole map of a user, decoded. Raises ValueError if the user or the map doesn't exist."""
        cursor = await self.connection.execute(
            """
            SELECT m.seed, m.width, m.height, m.spawn_x, m.spawn_y, m.terrain, m.biomes,
                   m.objects, m.animals, m.monsters, u.location_x, u.location_y
            FROM maps m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.user_id = ?
            """,
            (user_id,)
        )

        row = await cursor.fetchone()

        if row is None:
            if not await self.user_exists(user_id):
                raise ValueError("User not found.")
            raise ValueError("This user doesn't have a map yet.")

        return {
            'seed': row[0],
            'width': row[1],
            'height': row[2],
            'spawn': (row[3], row[4]),
            'terrain': mapgen.unpack_grid(row[5]),
            'biomes': mapgen.unpack_grid(row[6]),
            'objects': json.loads(row[7]),
            'animals': json.loads(row[8]),
            'monsters': json.loads(row[9]),
            'position': (row[10], row[11]),
        }

    async def _save_layer(self, user_id, layer_name, layer):
        if layer_name not in ('objects', 'animals', 'monsters'):
            raise ValueError("Invalid map layer.")

        await self.connection.execute(
            f"""
            UPDATE maps
            SET {layer_name} = ?
            WHERE user_id = ?
            """,
            (json.dumps(layer, separators=(',', ':')), user_id)
        )

    def _mobs(self, hostile):
        """The mobs.json entries that are hostile (monsters) or not (animals)."""
        return {mob_id: mob for mob_id, mob in self.mobs.items() if bool(mob.get('hostile')) == hostile}

    @staticmethod
    def _tiles_of(layer):
        return {mapgen.parse_key(key) for key in layer}

    async def generate_map(self, user_id, seed=None, populate=True):
        """
        Gives a user a brand new map (random seed unless one is given), puts the player on the spawn
        point and, if populate is True, fills it with objects, animals and monsters.
        Returns {'seed': ..., 'spawn': (x, y)}.
        """
        if not await self.user_exists(user_id):
            raise ValueError("User not found.")
        if await self.map_exists(user_id):
            raise ValueError("This user already has a map.")

        # the slow part (about 0.3s) runs BEFORE taking the lock so other commands aren't held up
        data = await mapgen.generate_terrain(seed)

        async with self.transaction_lock:
            try:
                # check again: something may have happened while the terrain was being generated
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")
                if await self.map_exists(user_id):
                    raise ValueError("This user already has a map.")

                await self.connection.execute(
                    """
                    INSERT INTO maps (user_id, seed, width, height, spawn_x, spawn_y, terrain, biomes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, data['seed'], data['width'], data['height'],
                        data['spawn'][0], data['spawn'][1],
                        mapgen.pack_grid(data['terrain']), mapgen.pack_grid(data['biomes'])
                    )
                )

                await self.connection.execute(
                    """
                    UPDATE users
                    SET location_x = ?, location_y = ?
                    WHERE user_id = ?
                    """,
                    (data['spawn'][0], data['spawn'][1], user_id)
                )

                if populate:
                    await self._generate_objects(user_id)
                    await self._generate_animals(user_id)
                    await self._generate_monsters(user_id)

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

        return {'seed': data['seed'], 'spawn': data['spawn']}

    async def delete_map(self, user_id):
        """Removes a user's map and puts them back at (0, 0), e.g. before generate_map() makes a new one."""
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")
                if not await self.map_exists(user_id):
                    raise ValueError("This user doesn't have a map yet.")

                await self.connection.execute(
                    """
                    DELETE FROM maps
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.execute(
                    """
                    UPDATE users
                    SET location_x = 0, location_y = 0
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def search_map(self, user_id, xy1=None, xy2=None):
        """
        The map, or just a rectangle of it: xy1 and xy2 are two opposite corners as (x, y), either order,
        corners are included, and anything outside the map is clamped to its edge. Leave both as None for
        the whole map (a missing one defaults to that corner of the map).

        Returns {
            'seed', 'width', 'height', 'player': (x, y),
            'x1', 'y1', 'x2', 'y2':  the rectangle that was actually returned,
            'terrain': [[tile name, ...], ...],    rows y1..y2, columns x1..x2
            'biomes':  [[biome name, ...], ...],
            'objects':  {(x, y): object_id},
            'animals':  {(x, y): {'id', 'hp'}},
            'monsters': {(x, y): {'id', 'hp'}},
        }  (all coordinates are absolute map coordinates)
        """
        m = await self._get_map(user_id)
        width, height = m['width'], m['height']

        def corner(point, default):
            if point is None:
                return default
            try:
                px, py = point
            except (TypeError, ValueError):
                raise ValueError("Coordinates must be (x, y).")
            if isinstance(px, bool) or isinstance(py, bool) or not isinstance(px, int) or not isinstance(py, int):
                raise ValueError("Coordinates must be whole numbers.")
            return min(max(px, 0), width - 1), min(max(py, 0), height - 1)

        ax, ay = corner(xy1, (0, 0))
        bx, by = corner(xy2, (width - 1, height - 1))
        x1, x2 = sorted((ax, bx))
        y1, y2 = sorted((ay, by))

        return self._slice_map(m, x1, y1, x2, y2)

    @staticmethod
    def _slice_map(m, x1, y1, x2, y2):
        """The rectangle (x1, y1)-(x2, y2) of an already decoded map, in the format search_map() returns."""
        width = m['width']

        terrain, biomes = [], []
        for y in range(y1, y2 + 1):
            start = y * width
            terrain.append([mapgen.TILES[b] for b in m['terrain'][start + x1:start + x2 + 1]])
            biomes.append([mapgen.BIOMES[b] for b in m['biomes'][start + x1:start + x2 + 1]])

        def inside(layer):
            result = {}
            for key, value in layer.items():
                x, y = mapgen.parse_key(key)
                if x1 <= x <= x2 and y1 <= y <= y2:
                    result[(x, y)] = value
            return result

        return {
            'seed': m['seed'], 'width': width, 'height': m['height'], 'player': m['position'],
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'terrain': terrain, 'biomes': biomes,
            'objects': inside(m['objects']), 'animals': inside(m['animals']), 'monsters': inside(m['monsters']),
        }

    async def get_map_view(self, user_id, cols=11, rows=7):
        """
        What the player sees: a cols x rows window of the map centred on them. Next to a map edge the
        window slides so it always stays full size (the player is then off-centre).
        Same format as search_map(), plus 'player_biome'.
        """
        for value in (cols, rows):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("The view size must be a positive whole number.")

        m = await self._get_map(user_id)
        width, height = m['width'], m['height']
        cols, rows = min(cols, width), min(rows, height)
        px, py = m['position']

        x1 = min(max(px - cols // 2, 0), width - cols)
        y1 = min(max(py - rows // 2, 0), height - rows)

        view = self._slice_map(m, x1, y1, x1 + cols - 1, y1 + rows - 1)
        view['player_biome'] = mapgen.BIOMES[m['biomes'][py * width + px]]
        return view

    async def get_tile(self, user_id, x, y):
        """Everything on one tile: {'x', 'y', 'tile', 'biome', 'walkable', 'object', 'animal', 'monster'}."""
        m = await self._get_map(user_id)

        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            raise ValueError("Coordinates must be whole numbers.")
        if not (0 <= x < m['width'] and 0 <= y < m['height']):
            raise ValueError("That tile is outside the map.")

        i = y * m['width'] + x
        key = mapgen.layer_key(x, y)
        object_id = m['objects'].get(key)

        return {
            'x': x, 'y': y,
            'tile': mapgen.TILES[m['terrain'][i]],
            'biome': mapgen.BIOMES[m['biomes'][i]],
            'walkable': m['terrain'][i] in mapgen.WALKABLE_IDS
                        and not (object_id and self.objects.get(object_id, {}).get('blocking', True))
                        and key not in m['animals'] and key not in m['monsters'],
            'object': object_id,
            'animal': m['animals'].get(key),
            'monster': m['monsters'].get(key),
        }

    async def move(self, user_id, x=None, y=None):
        """
        Walks the player x tiles right (negative = left) and y tiles down (negative = up), one tile at a
        time, horizontally first. Stops in front of anything in the way: the edge of the map, water,
        a blocking object (trees, rocks, ores...), an animal or a monster. Either argument can be None.

        Returns {'x', 'y': new position, 'moved': tiles walked, 'requested': tiles asked for,
                 'blocked_by': None or {'type': 'edge'|'water'|'object'|'animal'|'monster',
                                        'id': object/animal/monster id or None, 'x', 'y': the tile in the way}}
        """
        async with self.transaction_lock:
            try:
                for value in (x, y):
                    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                        raise ValueError("Distances must be whole numbers.")

                dx, dy = x or 0, y or 0
                if dx == 0 and dy == 0:
                    raise ValueError("Say how far to move on x and/or y.")
                if abs(dx) + abs(dy) > self.MAX_MOVE_STEPS:
                    raise ValueError(f"You can only move up to {self.MAX_MOVE_STEPS} tiles at a time.")

                m = await self._get_map(user_id)
                cx, cy = m['position']

                steps = [(1 if dx > 0 else -1, 0)] * abs(dx) + [(0, 1 if dy > 0 else -1)] * abs(dy)
                moved = 0
                blocked_by = None

                for step_x, step_y in steps:
                    nx, ny = cx + step_x, cy + step_y
                    key = mapgen.layer_key(nx, ny)

                    if not (0 <= nx < m['width'] and 0 <= ny < m['height']):
                        blocked_by = {'type': 'edge', 'id': None, 'x': nx, 'y': ny}
                    elif m['terrain'][ny * m['width'] + nx] not in mapgen.WALKABLE_IDS:
                        blocked_by = {'type': 'water', 'id': None, 'x': nx, 'y': ny}
                    elif key in m['monsters']:
                        blocked_by = {'type': 'monster', 'id': m['monsters'][key]['id'], 'x': nx, 'y': ny}
                    elif key in m['animals']:
                        blocked_by = {'type': 'animal', 'id': m['animals'][key]['id'], 'x': nx, 'y': ny}
                    elif key in m['objects'] and self.objects.get(m['objects'][key], {}).get('blocking', True):
                        blocked_by = {'type': 'object', 'id': m['objects'][key], 'x': nx, 'y': ny}

                    if blocked_by is not None:
                        break

                    cx, cy = nx, ny
                    moved += 1

                if moved > 0:
                    await self.connection.execute(
                        """
                        UPDATE users
                        SET location_x = ?, location_y = ?
                        WHERE user_id = ?
                        """,
                        (cx, cy, user_id)
                    )
                    await self.connection.commit()

                return {'x': cx, 'y': cy, 'moved': moved, 'requested': len(steps), 'blocked_by': blocked_by}

            except Exception:
                await self.connection.rollback()
                raise

    async def _generate_objects(self, user_id):
        m = await self._get_map(user_id)

        # leave the player's tile (and the one around it) and anything standing on the map free
        keep_free = self._tiles_of(m['animals']) | self._tiles_of(m['monsters'])
        for cx, cy in (m['position'], m['spawn']):
            keep_free |= {(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}

        layer = await asyncio.to_thread(
            mapgen.generate_objects_layer,
            m['seed'], m['width'], m['height'], m['terrain'], m['biomes'], self.objects, keep_free
        )
        await self._save_layer(user_id, 'objects', layer)
        return len(layer)

    async def _generate_animals(self, user_id):
        m = await self._get_map(user_id)
        taken = self._tiles_of(m['objects']) | self._tiles_of(m['monsters'])

        added = await asyncio.to_thread(
            mapgen.generate_entities_layer,
            random.Random(), m['width'], m['height'], m['terrain'], m['biomes'],
            self._mobs(hostile=False), m['animals'], taken, m['spawn'], m['position']
        )
        m['animals'].update(added)
        await self._save_layer(user_id, 'animals', m['animals'])
        return len(added)

    async def _generate_monsters(self, user_id):
        m = await self._get_map(user_id)
        taken = self._tiles_of(m['objects']) | self._tiles_of(m['animals'])

        added = await asyncio.to_thread(
            mapgen.generate_entities_layer,
            random.Random(), m['width'], m['height'], m['terrain'], m['biomes'],
            self._mobs(hostile=True), m['monsters'], taken, m['spawn'], m['position']
        )
        m['monsters'].update(added)
        await self._save_layer(user_id, 'monsters', m['monsters'])
        return len(added)

    async def generate_objects(self, user_id):
        """
        (Re)places every tree, rock and ore from objects.json according to the biomes. The layout is
        decided by the map's seed, so calling it again puts every resource back where it started.
        Returns how many objects the map has now.
        """
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

                count = await self._generate_objects(user_id)
                await self.connection.commit()
                return count

            except Exception:
                await self.connection.rollback()
                raise

    async def generate_animals(self, user_id):
        """
        Tops animals (the non-hostile mobs in mobs.json) up to their density for each biome. Existing animals stay where they
        are, so calling it again just respawns the ones that were killed.
        Returns how many new animals were added.
        """
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

                count = await self._generate_animals(user_id)
                await self.connection.commit()
                return count

            except Exception:
                await self.connection.rollback()
                raise

    async def generate_monsters(self, user_id):
        """
        Same as generate_animals() but for the hostile mobs in mobs.json. Tougher monsters only appear further from the
        spawn point (their 'min_distance'), and none spawn right next to the player.
        Returns how many new monsters were added.
        """
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

                count = await self._generate_monsters(user_id)
                await self.connection.commit()
                return count

            except Exception:
                await self.connection.rollback()
                raise

    async def _remove_from_layer(self, user_id, layer_name, x, y, label):
        async with self.transaction_lock:
            try:
                m = await self._get_map(user_id)
                key = mapgen.layer_key(x, y)

                if key not in m[layer_name]:
                    raise ValueError(f"There is no {label} at ({x}, {y}).")

                removed = m[layer_name].pop(key)
                await self._save_layer(user_id, layer_name, m[layer_name])
                await self.connection.commit()

                return removed

            except Exception:
                await self.connection.rollback()
                raise

    async def remove_object(self, user_id, x, y):
        """Takes the object off a tile (e.g. after it was chopped / mined). Returns its id."""
        return await self._remove_from_layer(user_id, 'objects', x, y, 'object')

    async def remove_animal(self, user_id, x, y):
        """Takes the animal off a tile (e.g. after it was killed). Returns {'id', 'hp'}."""
        return await self._remove_from_layer(user_id, 'animals', x, y, 'animal')

    async def remove_monster(self, user_id, x, y):
        """Takes the monster off a tile (e.g. after it was killed). Returns {'id', 'hp'}."""
        return await self._remove_from_layer(user_id, 'monsters', x, y, 'monster')
