import base64
import json
import os
import sqlite3
import time
import traceback
from collections import defaultdict
from io import BytesIO

import disnake
import python_nbt.nbt as nbt
import requests
from PIL import Image
from discord_webhook import DiscordWebhook
from disnake.ext import commands
from requests.adapters import HTTPAdapter
from requests.exceptions import JSONDecodeError
from threading import Thread
from urllib3.util.retry import Retry

import color
import config

session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

webhook = DiscordWebhook("https://discord.com/api/webhooks/1101276248279363585/rMVoiZYNNwrCUcdFU7OJ3sJ8d8ZJAXRJg6P4J0aT0PYEIW4X9u2Pej2c5SKJrazDz-gf")


class AuctionThread(Thread):
    def run(self):
        finder = AuctionScanner()
        finder.scan_auctions_loop()


def get_json(url):
    while True:
        try:
            resp = session.get(url, timeout=10)
            json_resp = resp.json()
            return json_resp
        except requests.exceptions.ConnectionError as e:
            print(f"Connection Error! {str(e)}"
                  "\nThis is most likely Hypixel's fault, just wait it out.")
        except requests.exceptions.Timeout:
            print("Request timed out.")
        except JSONDecodeError as e:
            print("thomas' fault.")
            print(e)
            return None
        except Exception as e:
            print("Unexpected Error!"
                  f"\n{str(e)}")
            traceback.print_tb(e.__traceback__)


bot = commands.InteractionBot()

with open(os.path.join(os.path.dirname(__file__), 'default_hexes.json'), "r") as r:
    default_hexes = json.load(r)

hex_list = []
for armour_type, armour_data in default_hexes.items():
    for skyblock_id, item_hex in armour_data.items():
        if item_hex not in hex_list:
            hex_list.append(item_hex)
        armour_data[skyblock_id] = color.hex_to_lab(item_hex)


class SeymourPiece:
    def __init__(self, item_id, item_uuid, hex_code, armor_type):
        self.item_id = item_id
        self.item_uuid = item_uuid
        self.hex_code = hex_code
        self.armor_type = armor_type

    def get_closest(self, new_method: bool = True, length: int = 1):
        lab1 = color.hex_to_lab(self.hex_code)
        closest_list = defaultdict(list)
        for skyblock_item, lab2 in {**default_hexes[self.armor_type], **default_hexes["OTHER"]}.items():
            if new_method:
                similarity = color.compare_delta_e_2000(lab1, lab2)
            else:
                similarity = color.compare_delta_cie(lab1, lab2)
            closest_list[similarity].append(skyblock_item)

        closest_list = [(y, x) for x, y in closest_list.items()]
        closest_list = sorted(closest_list, key=lambda x: x[1])
        crystal_found, fairy_found = False, False
        for data in closest_list:
            pieces, sim = data
            to_remove = []
            for piece in pieces:
                if piece.startswith("CRYSTAL_"):
                    if crystal_found:
                        to_remove.append(piece)
                    crystal_found = True
                elif piece.startswith("FAIRY_"):
                    if fairy_found:
                        to_remove.append(piece)
                    fairy_found = True
            for piece in to_remove:
                pieces.remove(piece)
        closest_list = [(', '.join(data[0]), data[1]) for data in closest_list if len(data[0]) > 0]
        return closest_list[0:length]

    def create_armor_image(self):
        armor_path = f"a/leather_{self.armor_type.lower()}.png"
        armor_overlay_path = f"a/leather_{self.armor_type.lower()}_overlay.png"
        overlay_color = tuple(int(self.hex_code[i:i + 2], 16) for i in (0, 2, 4))

        grayscale_image = Image.open(armor_path)
        light_array = grayscale_image.convert('L')
        rgba_array = grayscale_image.convert('RGBA')

        result_image = Image.new('RGBA', rgba_array.size)

        for x in range(light_array.width):
            for y in range(light_array.height):
                light_value = light_array.getpixel((x, y))
                adjusted_color = tuple(int(c * (light_value / 255)) for c in overlay_color)

                alpha = rgba_array.getpixel((x, y))[-1]
                rgba = adjusted_color + (alpha,)

                result_image.putpixel((x, y), rgba)

        overlay_image = Image.open(armor_overlay_path)
        result_image.paste(overlay_image, (0, 0), mask=overlay_image)
        result_image = result_image.resize((128, 128), resample=Image.BOX)
        return result_image


class SeymourPieceWithOwnership:
    def __init__(self, piece: SeymourPiece, owner_uuid: str, location: str, last_seen: int):
        self.piece = piece
        self.owner_uuid = owner_uuid
        self.location = location
        self.last_seen = last_seen


class SeymourDatabase:
    def __init__(self):
        self.con = sqlite3.connect("seymour_pieces.db")

    def item_exists(self, item_uuid):
        with self.con:
            res = self.con.execute('SELECT item_uuid FROM seymour_pieces WHERE item_uuid = ?', (item_uuid,))
            return res.fetchone() is not None

    def existing_items(self, item_uuids: list[str]) -> set[str]:
        with self.con:
            res = self.con.execute(
                f'SELECT item_uuid FROM seymour_pieces WHERE item_uuid IN ({",".join(["?"] * len(item_uuids))})',
                tuple(item_uuids))
            return set(x[0] for x in res.fetchall())

    def matching_hexes(self, hex_code, item_uuid):
        with self.con:
            res = self.con.execute(
                "SELECT * FROM seymour_pieces WHERE hex_code = ? and item_uuid != ?",
                (hex_code, item_uuid))
        return res.fetchall()

    def insert_item(self, item_id, item_uuid, owner, location, last_seen, hex_code):
        with self.con:
            self.con.execute("INSERT INTO seymour_pieces VALUES (?, ?, ?, ?, ?, ?)",
                             (item_id, item_uuid, owner, location, last_seen, hex_code))

    def insert_items(self, pieces: dict[str, SeymourPieceWithOwnership]):
        with self.con:
            for piece in pieces.values():
                self.con.execute("INSERT INTO seymour_pieces VALUES (?, ?, ?, ?, ?, ?)",
                                 (piece.piece.item_id, piece.piece.item_uuid, piece.owner_uuid,
                                  piece.location, piece.last_seen, piece.piece.hex_code))

    def update_item(self, item_uuid, owner, location, last_seen):
        with self.con:
            res = self.con.execute('SELECT last_seen FROM seymour_pieces WHERE item_uuid = ?', (item_uuid,))
            current_last_seen = res.fetchone()
            if current_last_seen is None:  # not me checking this one twice
                return
            if last_seen < current_last_seen[0]:
                return

            self.con.execute(
                "UPDATE seymour_pieces SET owner = ?, location = ?, last_seen = ? WHERE item_uuid = ?",
                (owner, location, last_seen, item_uuid)
            )

    def update_items(self, pieces: dict[str, SeymourPieceWithOwnership]):
        with self.con:
            res = self.con.execute(
                f'SELECT item_uuid,last_seen FROM seymour_pieces WHERE item_uuid IN ({",".join(["?"] * len(pieces))})',
                tuple(pieces.keys()))
            for data in res.fetchall():
                current_last_seen = data[1]
                piece_with_ownership_data = pieces[data[0]]
                if piece_with_ownership_data.last_seen < current_last_seen:
                    continue
                self.con.execute(
                    "UPDATE seymour_pieces SET owner = ?, location = ?, last_seen = ? WHERE item_uuid = ?",
                    (piece_with_ownership_data.owner_uuid, piece_with_ownership_data.location,
                     piece_with_ownership_data.last_seen, piece_with_ownership_data.piece.item_uuid)
                )

    def add_item_to_db(self, piece: SeymourPiece, owner, location, last_seen):
        if self.item_exists(piece.item_uuid):
            self.update_item(piece.item_uuid, owner, location, last_seen)
        else:
            self.insert_item(piece.item_id, piece.item_uuid, owner, location, last_seen, piece.hex_code)

        self.con.commit()

    def add_items_to_db(self, pieces: list[SeymourPieceWithOwnership]):
        item_uuids = {x.piece.item_uuid: x for x in pieces}
        existing_uuids = self.existing_items(list(item_uuids.keys()))
        existing_items = {x: item_uuids[x] for x in existing_uuids}
        bad_items = {x: y for x, y in item_uuids.items() if x not in existing_uuids}

        if len(existing_items):
            self.update_items(existing_items)

        if len(bad_items):
            self.insert_items(bad_items)

        self.con.commit()

    def close_connection(self):
        self.con.close()


class AuctionScanner:
    def __init__(self):
        self.API_URL = "https://api.hypixel.net"
        self.db = SeymourDatabase()

    @staticmethod
    def human_format(num):
        num = float('{:.3g}'.format(num))
        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0
        return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])

    @staticmethod
    def send_to_webhook(content=None, embed=None, file_path=None):
        webhook.set_content(content)
        webhook.add_embed(embed)
        with open(file_path, 'rb') as armor_file:
            webhook.add_file(armor_file.read(), "armor_image.png")

        webhook.execute(remove_embeds=True)

    def send_item_to_webhook(self, seymour_piece, auction):
        closest_list = seymour_piece.get_closest(length=3)
        closest_list_old = seymour_piece.get_closest(new_method=False, length=3)

        content = ""
        if closest_list[0][1] < 1.0:
            content = "<@&1103413230682001479>"

        try:
            seller_ign = get_json(f"https://sessionserver.mojang.com/session/minecraft/profile/{auction['auctioneer']}")['name']
        except KeyError:
            seller_ign = "Unknown"
        print("Auction Found!")
        print(
            f"Seller: {seller_ign}, Piece: {(seymour_piece.item_id, seymour_piece.item_uuid, seymour_piece.hex_code)}")

        embed_title = auction['item_name']
        dupes = self.db.matching_hexes(seymour_piece.hex_code, seymour_piece.item_uuid)
        if dupes is not None and len(dupes):
            print(f"{len(dupes)} match(es) found!")
            for dupe in dupes:
                try:
                    owner_ign = get_json(f"https://sessionserver.mojang.com/session/minecraft/profile/{dupe[2]}")['name']
                except KeyError:
                    owner_ign = "Unknown"
                print(f"Last Known Owner: {owner_ign}, Piece: {dupe}")
            embed_title = embed_title.replace(" ", "  ")
        print()

        piece = seymour_piece.create_armor_image()
        piece.save("a/armor_piece.png")

        embed = {
            "title": embed_title,
            "url": f"https://sky.coflnet.com/auction/{auction['uuid']}",
            "color": int(seymour_piece.hex_code, 16),
            "author": {
                "name": seller_ign,
                "icon_url": f"https://crafatar.com/renders/head/{auction['auctioneer']}"
            },
            "thumbnail": {
                "url": f"attachment://armor_image.png"
            },
            "fields": [
                {
                    "name": "Hex",
                    "value": f"#{seymour_piece.hex_code}",
                    "inline": True
                },
                {
                    "name": "Price" if auction['bin'] else "Starting Bid",
                    "value": self.human_format(auction['starting_bid']),
                    "inline": True
                },
                {
                    "name": "Closest Armor Pieces (new method)",
                    "value": f"{closest_list[0][0].replace('_', ' ').title()}: {round(closest_list[0][1], 2)}\n"
                             f"{closest_list[1][0].replace('_', ' ').title()}: {round(closest_list[1][1], 2)}\n"
                             f"{closest_list[2][0].replace('_', ' ').title()}: {round(closest_list[2][1], 2)}",
                    "inline": False
                },
                {
                    "name": "Closest Armor Pieces (old method)",
                    "value": f"{closest_list_old[0][0].replace('_', ' ').title()}: {round(closest_list_old[0][1], 2)}\n"
                             f"{closest_list_old[1][0].replace('_', ' ').title()}: {round(closest_list_old[1][1], 2)}\n"
                             f"{closest_list_old[2][0].replace('_', ' ').title()}: {round(closest_list_old[2][1], 2)}",
                    "inline": False
                }
            ],
            "footer": {
                "text": str(f"/viewauction {auction['uuid']}")
            }
        }

        self.send_to_webhook(content=content, embed=embed, file_path="a/armor_piece.png")

    @staticmethod
    def get_nbt_data(auction):
        nbt_data = nbt.read_from_nbt_file(file=BytesIO(base64.b64decode(auction['item_bytes'])))
        nbt_data = nbt_data.json_obj(full_json=False)
        return nbt_data

    def get_item_from_auction(self, auction):
        nbt_data = self.get_nbt_data(auction)
        item_id = str(nbt_data["i"][0]["tag"]["ExtraAttributes"]["id"])
        item_uuid = str(nbt_data['i'][0]['tag']['ExtraAttributes']['uuid'])
        hex_code = hex(nbt_data["i"][0]["tag"]["display"]["color"]).replace("0x", "").upper().rjust(6, '0')
        match item_id:
            case "VELVET_TOP_HAT":
                armor_type = "HELMET"
            case "CASHMERE_JACKET":
                armor_type = "CHESTPLATE"
            case "SATIN_TROUSERS":
                armor_type = "LEGGINGS"
            case "OXFORD_SHOES":
                armor_type = "BOOTS"
            case _:
                return

        seymour_piece = SeymourPiece(item_id, item_uuid, hex_code, armor_type)
        self.db.add_item_to_db(seymour_piece, auction['auctioneer'], "auction_house", int(time.time()))
        self.send_item_to_webhook(seymour_piece, auction)

    def find_items(self, auction_page):
        if len(auction_page['auctions']) == 0:
            print(f"Empty auctions page: {json.dumps(auction_page, indent=4)}")
        for auction in auction_page['auctions']:
            if all(i not in auction['item_name'] for i in
                   ["Velvet Top Hat", "Cashmere Jacket", "Satin Trousers", "Oxford Shoes"]):
                continue
            if auction['start'] < (time.time() - 60) * 1000:
                continue
            if auction['claimed']:
                continue

            self.get_item_from_auction(auction)

    def scan_auctions_loop(self):
        last_update = get_json(f"https://api.hypixel.net/skyblock/auctions?page=0")['lastUpdated']
        while True:
            download_start = time.time_ns()
            c = get_json(f"https://api.hypixel.net/skyblock/auctions?page=0")
            if c is None:
                time.sleep(5)
                continue
            download_end = time.time_ns()
            if last_update < c['lastUpdated']:
                start = time.time()
                last_update = c['lastUpdated']
                find_start = time.time_ns()
                self.find_items(c)
                find_end = time.time_ns()
                print(f"Refresh completed!\n"
                      f"Download time: {(download_end - download_start) / 1e6}ms\n"
                      f"Processing time: {(find_end - find_start) / 1e6}ms\n")
                time.sleep(max((start + 55) - time.time(), 1))
                continue
            time.sleep(0.1)


class PlayerScanner:
    def __init__(self):
        self.items = []
        self.seymour_list = {}
        self.menus_to_check = ["inv_contents", "inv_armor", "wardrobe_contents", "ender_chest_contents",
                               "backpack_contents", "personal_vault_contents"]
        self.key = config.api_key
        self.player = {}
        self.uuid = ""
        self.db = SeymourDatabase()

    def get_uuid(self, input_name):
        self.seymour_list = {}
        try:
            player_info = get_json(f"https://api.mojang.com/users/profiles/minecraft/{input_name}")
            name = player_info['name']
            uuid = player_info['id']
        except KeyError:
            try:
                player_info = get_json(f"https://api.ashcon.app/mojang/v2/user/{input_name}")
                name = player_info['name']
                uuid = player_info['uuid'].replace("-", "")
            except KeyError:
                return
        self.uuid = uuid
        return name, uuid

    def set_uuid(self, uuid):
        self.uuid = uuid
        self.seymour_list = {}

    def get_profile(self):
        s = time.time_ns()
        self.player = get_json(f"https://api.hypixel.net/skyblock/profiles?uuid={self.uuid}&key={self.key}")
        if self.player is None:
            return
        if self.player.get('profiles') is None:
            return
        # print(f"Download from Hypixel {(time.time_ns() - s) / 1e6}ms")

        s = time.time_ns()
        for profile in self.player['profiles']:
            if self.uuid not in profile['members']:
                continue
            for menu in self.menus_to_check:
                if menu == "backpack_contents":
                    backpacks = profile['members'][self.uuid].get(menu)
                    if backpacks is None:
                        continue
                    for i, backpack in backpacks.items():
                        self.add_inventory(backpack, f"{menu}_{i}")
                else:
                    inventory = profile['members'][self.uuid].get(menu)
                    if inventory is None:
                        continue
                    self.add_inventory(inventory, menu)
        # print(f"Process Hypixel data {(time.time_ns() - s) / 1e6}ms")

    def add_inventory(self, inventory, inventory_name):
        if inventory.get('data') is None:
            return
        try:
            decoded = nbt.read_from_nbt_file(file=BytesIO(base64.b64decode(inventory['data'])))
        except Exception as e:
            print("Something went wrong! " + str(e))
            print(self.uuid, inventory_name)
            return
        decoded = decoded.json_obj(full_json=False)

        for item in decoded['i']:
            item = item.get("tag")
            if item is None:
                continue
            if 'ExtraAttributes' not in item:
                continue
            if 'id' not in item['ExtraAttributes']:
                continue
            if str(item['ExtraAttributes']['id']) not in (
                    "VELVET_TOP_HAT", "CASHMERE_JACKET", "SATIN_TROUSERS", "OXFORD_SHOES"):
                continue
            hex_code = hex(item['display']['color']).replace("0x", "").upper().rjust(6, '0')

            self.seymour_list[str(item['ExtraAttributes'].get('uuid', "NONE"))] = {
                "item_id": str(item['ExtraAttributes']['id']),
                "uuid": str(item['ExtraAttributes'].get('uuid', "NONE")),
                "last_seen": int(time.time()),
                "location": inventory_name,
                "hex": hex_code
            }

    def add_i_tem_data(self):
        url = f"https://api.tem.cx/items/player/{self.uuid}"
        s = time.time_ns()

        i_item_list = get_json(url)
        if i_item_list is None:
            return

        # print(f"Download from iTEM {(time.time_ns() - s) / 1e6}ms")

        s = time.time_ns()

        for item in i_item_list['items']:
            if item['_id'] in self.seymour_list:
                continue
            if item['itemId'] not in ("VELVET_TOP_HAT", "CASHMERE_JACKET", "SATIN_TROUSERS", "OXFORD_SHOES"):
                continue
            self.seymour_list[item['_id']] = {
                "item_id": item['itemId'],
                "uuid": item['_id'],
                "last_seen": int(item['lastChecked'] / 1000),
                "location": "item_history",
                "hex": item['colour']
            }
        # print(f"Process iTEM data {(time.time_ns() - s) / 1e6}ms")

    def process_seymour_list(self):
        # SLOW
        pieces = []
        for item in self.seymour_list.values():
            match item['item_id']:
                case "VELVET_TOP_HAT":
                    armor_type = "HELMET"
                case "CASHMERE_JACKET":
                    armor_type = "CHESTPLATE"
                case "SATIN_TROUSERS":
                    armor_type = "LEGGINGS"
                case "OXFORD_SHOES":
                    armor_type = "BOOTS"
                case _:
                    return
            seymour_piece = SeymourPiece(item['item_id'], item['uuid'], item['hex'], armor_type)
            pieces.append(SeymourPieceWithOwnership(seymour_piece, self.uuid, item['location'], item['last_seen']))

            closest_item = seymour_piece.get_closest()[0]
            item['closest'] = closest_item

        self.db.add_items_to_db(pieces)

        sorted_list = sorted(list(self.seymour_list.values()), key=lambda x: x['closest'][1])
        return sorted_list


@bot.event
async def on_ready():
    await bot.change_presence(
        activity=disnake.Activity(
            type=disnake.ActivityType.playing,
            name="with Hex Codes"
        )
    )

    print('Connected to bot: {}'.format(bot.user.name))
    print('Bot ID: {}'.format(bot.user.id))


@bot.slash_command(
    name="compare",
    description="Compares two given hex codes, mostly for testing purposes.",
    dm_permission=False
)
async def compare(
        inter: disnake.AppCommandInteraction,
        hex_code_1: str = commands.Param(name="hex1", description="The hex code of the item.", min_length=6,
                                         max_length=6),
        hex_code_2: str = commands.Param(name="hex2", description="The hex code of the item.", min_length=6,
                                         max_length=6)
):
    await inter.response.defer()

    rgb = tuple(int(hex_code_1[i:i + 2], 16) for i in (0, 2, 4))
    xyz = color.rgb_to_xyz(rgb)
    lab1 = color.xyz_to_cielab(xyz)
    rgb = tuple(int(hex_code_2[i:i + 2], 16) for i in (0, 2, 4))
    xyz = color.rgb_to_xyz(rgb)
    lab2 = color.xyz_to_cielab(xyz)

    cie_76_sim = color.compare_delta_cie(lab1, lab2)
    cie_de00_sim = color.compare_delta_e_2000(lab1, lab2)

    embed = disnake.Embed(
        title=f"Similarities between #{hex_code_1.upper()} and #{hex_code_2.upper()}:",
        colour=int("00FF00", 16),
    )
    embed.add_field(
        name="CIE Lab value",
        value=cie_76_sim,
        inline=True
    )
    embed.add_field(
        name="Delta E 2000 value",
        value=cie_de00_sim,
        inline=True
    )
    await inter.edit_original_message(embed=embed)


@bot.slash_command(
    name="closest_pieces",
    description="Checks for the closest SkyBlock pieces to a given hex code.",
    dm_permission=False
)
async def closest(
        inter: disnake.AppCommandInteraction,
        hex_code: str = commands.Param(name="hex", description="The hex code of the item.", min_length=6, max_length=6),
        armor_type: str = commands.Param(
            name="piece",
            description="The type of armor piece the item is.",
            choices={"Helmet": "HELMET", "Chestplate": "CHESTPLATE", "Leggings": "LEGGINGS", "Boots": "BOOTS"}
        ),
        new_method: bool = True
):
    await inter.response.defer()
    seymour_piece = SeymourPiece("", "", hex_code, armor_type)
    closest_list = seymour_piece.get_closest(new_method=new_method, length=3)

    piece = seymour_piece.create_armor_image()
    piece.save("a/armor_piece.png")

    embed = disnake.Embed(
        title=f"Closest SkyBlock pieces to hex code #{hex_code.upper()}:",
        description=f"{closest_list[0][0].replace('_', ' ').title()}: {round(closest_list[0][1], 2)}\n"
                    f"{closest_list[1][0].replace('_', ' ').title()}: {round(closest_list[1][1], 2)}\n"
                    f"{closest_list[2][0].replace('_', ' ').title()}: {round(closest_list[2][1], 2)}",
        colour=int(hex_code, 16)
    )
    embed.set_thumbnail(file=disnake.File("a/armor_piece.png"))
    await inter.edit_original_message(embed=embed)


@bot.slash_command(
    name="find_closest_hex",
    description="does absolutely nothing!",
    dm_permission=False
)
@commands.default_member_permissions(administrator=True)
async def find_closest_hex(inter: disnake.AppCommandInteraction, hex_code: str, item_id=None, owner=None):
    await inter.response.defer()
    dupes_con = sqlite3.connect("seymour_pieces.db")
    dupes_cur = dupes_con.cursor()

    res = dupes_cur.execute("SELECT item_uuid,hex_code FROM seymour_pieces")
    all_hexes = res.fetchall()
    if all_hexes is None:
        await inter.edit_original_message("it broke")
        return

    item_dict = {}
    lab1 = color.hex_to_lab(hex_code)
    for item in all_hexes:
        lab2 = color.hex_to_lab(item[1])
        similarity = color.compare_delta_e_2000(lab1, lab2)
        if similarity > 5:
            continue
        item_dict[item[0]] = similarity

    res = dupes_cur.execute(f"SELECT * FROM seymour_pieces WHERE item_uuid IN ({','.join(['?'] * len(item_dict))})",
                            tuple(item_dict.keys()))
    good_items = res.fetchall()
    if good_items is None:
        await inter.edit_original_message("it broke")
        return
    for item in good_items.copy():
        if item_id is not None and item[0] != item_id:
            good_items.remove(item)
            item_dict.pop(item[1])
            continue
        if owner is not None and owner != item[2]:
            good_items.remove(item)
            item_dict.pop(item[1])
            continue
        item_with_sim = item + (item_dict[item[1]],)
        item_dict[item[1]] = list(item_with_sim)

    item_dict = sorted(list(item_dict.values()), key=lambda x: x[-1])
    resp_string = ""
    for item in item_dict[0:10]:
        resp_string += str(item) + '\n'
    await inter.edit_original_message(resp_string)


@bot.slash_command(
    name="check_dupes",
    description="does absolutely nothing!",
    dm_permission=False
)
@commands.default_member_permissions(administrator=True)
async def check_dupes(inter: disnake.AppCommandInteraction, name=None):
    await inter.response.defer()
    dupes_db = SeymourDatabase()
    uuid = get_json(f"https://api.mojang.com/users/profiles/minecraft/{name}")['id']
    if name:
        with dupes_db.con:
            res = dupes_db.con.execute("SELECT * FROM seymour_pieces WHERE hex_code IN (SELECT hex_code FROM seymour_pieces WHERE owner = ?) AND hex_code IN (SELECT hex_code FROM seymour_pieces GROUP BY hex_code HAVING COUNT(DISTINCT owner) > 1 ) ORDER BY hex_code", (uuid,))
            dupes = res.fetchall()
            if dupes is None:
                await inter.edit_original_message("found nothing L")
    else:
        with dupes_db.con:
            res = dupes_db.con.execute("SELECT t.* FROM seymour_pieces t JOIN (SELECT hex_code FROM seymour_pieces GROUP BY hex_code HAVING COUNT(*) > 1 ) d ON t.hex_code = d.hex_code")
            dupes = res.fetchall()
            if dupes is None:
                await inter.edit_original_message("found nothing L")

    dupes_sorted = {}
    for dupe in dupes:
        if dupe[5] in dupes_sorted:
            dupes_sorted[dupe[5]].append(dupe)
        else:
            dupes_sorted[dupe[5]] = [dupe]

    for hex_code, items in dupes_sorted.items():
        print(f"Dupe Found! Hex: #{hex_code}")
        for x in items:
            print(x)

    await inter.edit_original_message("does nothing mean nothing to you")


@bot.slash_command(
    name="test_command",
    description="dw about it",
    dm_permission=False
)
async def test_command(inter: disnake.AppCommandInteraction, param):
    await inter.response.defer()
    dupes_con = sqlite3.connect("seymour_pieces.db")
    dupes_cur = dupes_con.cursor()

    res = dupes_cur.execute("SELECT * FROM seymour_pieces WHERE hex_code LIKE ?", (param,))
    duplicates = res.fetchall()
    if duplicates is None:
        await inter.edit_original_message("you used it wrong go away")
        return

    for item in duplicates:
        print(item)

    await inter.edit_original_message("it maybe worked but only arti can see it :(")


@bot.slash_command(
    name="check_poifect",
    description="does absolutely nothing!",
    dm_permission=False
)
@commands.default_member_permissions(administrator=True)
async def check_perfect(inter: disnake.AppCommandInteraction):
    await inter.response.defer()
    perfect_db = SeymourDatabase()
    with perfect_db.con:
        res = perfect_db.con.execute(
            f"SELECT * FROM seymour_pieces WHERE hex_code IN ({','.join(['?'] * len(hex_list))})", tuple(hex_list))
        perfects = res.fetchall()
        if perfects is None:
            await inter.edit_original_message("none found")
            return

    perfect_db.close_connection()
    print(perfects)
    await inter.edit_original_message("does nothing mean nothing to you")


@bot.slash_command(
    name="scan_player",
    description="Returns all of the Seymour's Special pieces owned by a player, sorted by similarity.",
    dm_permission=False
)
async def scan_player(inter: disnake.AppCommandInteraction, input_name: str, length: int = 5,
                      include_item: bool = True):
    s = time.time_ns()
    await inter.response.defer()
    print(f"Defer command {(time.time_ns() - s) / 1e6}ms")
    s = time.time_ns()
    scanner = PlayerScanner()
    print(f"Create Scanner object {(time.time_ns() - s) / 1e6}ms")
    s = time.time_ns()
    name, uuid = scanner.get_uuid(input_name)
    print(f"Get UUID from name {(time.time_ns() - s) / 1e6}ms")

    scanner.get_profile()
    if include_item:
        scanner.add_i_tem_data()

    s = time.time_ns()
    seymour_list = scanner.process_seymour_list()
    print(f"Process Seymour list {(time.time_ns() - s) / 1e6}ms")

    s = time.time_ns()
    if not len(seymour_list):
        await inter.edit_original_message(f"{name} has no known Seymour pieces.")
        return
    response_string = f"```{name}'s total pieces: {len(seymour_list)}```"

    for i in range(min(len(seymour_list), length)):
        response_string += f"`{seymour_list[i]['item_id']}` in `{seymour_list[i]['location']}`, hex: `#{seymour_list[i]['hex']}`, closest: `{seymour_list[i]['closest']}`\n"
    print(f"Made response {(time.time_ns() - s) / 1e6}ms")
    s = time.time_ns()
    await inter.edit_original_message(response_string)
    print(f"Edit message {(time.time_ns() - s) / 1e6}ms")


def main():
    finder = AuctionThread()
    finder.start()

    print("Auction Tracking Started")

    bot.run(config.bot_token)


if __name__ == '__main__':
    main()
