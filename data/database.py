import aiosqlite
import json
import asyncio

class MainDB:
    def __init__(self):
        self.connection: aiosqlite.Connection | None = None
        self.transaction_lock = asyncio.Lock()
        with open('data/items.json', 'r', encoding='utf-8') as file:
            self.items = json.load(file)

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
                axe DEFAULT NULL,
                fishing_rod DEFAULT NULL,

                location_x INTEGER DEFAULT 0,
                location_y INTEGER DEFAULT 0
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

                await self.connection.commit()

            except Exception:
                await self.connection.rollback()
                raise

    async def equip_item(self, user_id, item_id):
        async with self.transaction_lock:
            try:
                if not await self.user_exists(user_id):
                    raise ValueError("User not found.")

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

    async def add_exp(self, user_id, amount:int):
        async with self.transaction_lock:
            try:
                if not isinstance(amount, int) or amount <= 0:
                    raise ValueError('EXP amount must be greater than 0.')
                user_info = await self.get_user_info(user_id)

                lvl = user_info['level']
                exp = user_info['exp']+amount
                required_exp = int(100 * (1.45 ** (lvl - 1)))

                while exp >= required_exp:
                    exp -= required_exp
                    lvl += 1
                    required_exp = int(100 * (1.45 ** (lvl - 1)))

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
