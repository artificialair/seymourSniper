import json
import sqlite3
import time
import traceback
from base64 import b64decode
from collections import defaultdict
from datetime import datetime, timedelta
from pytz import timezone
from io import BytesIO
from threading import Thread

import disnake
import python_nbt.nbt as nbt
import requests
from PIL import Image
from discord_webhook import DiscordWebhook, DiscordEmbed
from disnake.ext import commands
from requests.adapters import HTTPAdapter
from requests.exceptions import JSONDecodeError
from urllib3.util.retry import Retry

import color
import config
import exotics

session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

bot = commands.InteractionBot()

with open('default_hexes.json', "r") as r:
    default_hexes = json.load(r)

with open('museum_info.json', "r") as r:
    oldest_items = json.load(r)

RARE_UNOBTAINABLE_ITEMS = ['REINFORCED_IRON_ARROW', 'GOLD_TIPPED_ARROW', 'REDSTONE_TIPPED_ARROW', 'EMERALD_TIPPED_ARROW', 'BOUNCY_ARROW', 'ICY_ARROW', 'ARMORSHRED_ARROW', 'EXPLOSIVE_ARROW', 'GLUE_ARROW', 'NANSORB_ARROW']
OG_REFORGE_LIST = ["godly", "unpleasant", "keen", "superior", "forceful", "hurtful", "demonic", "strong", "zealous"]
DUNGEON_ITEM_LIST = ["ROTTEN_HELMET", "ROTTEN_CHESTPLATE", "ROTTEN_LEGGINGS", "ROTTEN_BOOTS", "ZOMBIE_SOLDIER_HELMET", "ZOMBIE_SOLDIER_CHESTPLATE", "ZOMBIE_SOLDIER_LEGGINGS", "ZOMBIE_SOLDIER_BOOTS", "ZOMBIE_KNIGHT_HELMET", "ZOMBIE_KNIGHT_CHESTPLATE", "ZOMBIE_KNIGHT_LEGGINGS", "ZOMBIE_KNIGHT_BOOTS", "ZOMBIE_COMMANDER_HELMET", "ZOMBIE_COMMANDER_CHESTPLATE", "ZOMBIE_COMMANDER_LEGGINGS", "ZOMBIE_COMMANDER_BOOTS", "ZOMBIE_LORD_HELMET", "ZOMBIE_LORD_CHESTPLATE", "ZOMBIE_LORD_LEGGINGS", "ZOMBIE_LORD_BOOTS", "HEAVY_HELMET", "HEAVY_CHESTPLATE", "HEAVY_LEGGINGS", "HEAVY_BOOTS", "SUPER_HEAVY_HELMET", "SUPER_HEAVY_CHESTPLATE", "SUPER_HEAVY_LEGGINGS", "SUPER_HEAVY_BOOTS", "SKELETON_GRUNT_HELMET", "SKELETON_GRUNT_CHESTPLATE", "SKELETON_GRUNT_LEGGINGS", "SKELETON_GRUNT_BOOTS", "SKELETON_SOLDIER_HELMET", "SKELETON_SOLDIER_CHESTPLATE", "SKELETON_SOLDIER_LEGGINGS", "SKELETON_SOLDIER_BOOTS", "SKELETON_MASTER_HELMET", "SKELETON_MASTER_CHESTPLATE", "SKELETON_MASTER_LEGGINGS", "SKELETON_MASTER_BOOTS", "SKELETON_LORD_HELMET", "SKELETON_LORD_CHESTPLATE", "SKELETON_LORD_LEGGINGS", "SKELETON_LORD_BOOTS", "BOUNCY_HELMET", "BOUNCY_CHESTPLATE", "BOUNCY_LEGGINGS", "BOUNCY_BOOTS", "SKELETOR_HELMET", "SKELETOR_CHESTPLATE", "SKELETOR_LEGGINGS", "SKELETOR_BOOTS", "SNIPER_HELMET", "ZOMBIE_SOLDIER_CUTLASS", "ZOMBIE_KNIGHT_SWORD", "ZOMBIE_COMMANDER_WHIP", "CRYPT_DREADLORD_SWORD", "CRYPT_BOW", "MACHINE_GUN_BOW", "SNIPER_BOW", "CONJURING_SWORD", "EARTH_SHARD", "SILENT_DEATH", "ICE_SPRAY_WAND"]


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


temp_item_hashes = get_json("https://raw.githubusercontent.com/Altpapier/Skyblock-Item-Emojis/main/v3/itemHash.json")
temp_hash_images = get_json("https://raw.githubusercontent.com/Altpapier/Skyblock-Item-Emojis/main/v3/images.json")
item_images = {}
for temp_item_id, temp_item_hash in temp_item_hashes.items():
    if temp_item_hash not in temp_hash_images:
        continue
    item_images[temp_item_id] = temp_hash_images[temp_item_hash]['normal']


def send_to_webhook(webhook_name="bs", content=None, embed=None, file_path=None):
    if webhook_name == "seymour":
        webhook = DiscordWebhook(config.seymour_webhook_url)
    elif webhook_name == "museum":
        webhook = DiscordWebhook(config.museum_webhook_url)
    elif webhook_name == "exotic":
        webhook = DiscordWebhook(config.exotic_webhook_url)
    else:
        webhook = DiscordWebhook(config.bs_webhook_url)

    if content:
        webhook.set_content(content)
    if embed:
        webhook.add_embed(embed)
    if file_path:
        with open(file_path, "rb") as attachment:
            webhook.add_file(attachment.read(), "armor_image.png")
    webhook.execute(remove_embeds=True)
    webhook.set_content("")


def get_name_and_uuid(input_name=None, input_uuid=None):
    if input_name:
        url_to_call = f"https://api.mojang.com/users/profiles/minecraft/{input_name}"
    elif input_uuid:
        url_to_call = f"https://api.mojang.com/user/profile/{input_uuid}"
    else:
        print("nice one idiot")
        return "Unknown", "Unknown"

    try:
        player_info = get_json(url_to_call)
        name = player_info['name']
        uuid = player_info['id']
        return name, uuid
    except KeyError:  # for when mojang breaks
        pass

    try:
        player_info = get_json(f"https://api.ashcon.app/mojang/v2/user/{input_name if input_name else input_uuid}")
        name = player_info['username']
        uuid = player_info['uuid'].replace("-", "")
        return name, uuid
    except KeyError:  # for when it breaks
        return "Unknown", "Unknown"


class SeymourPiece:
    def __init__(self, item_id: str, item_uuid: str, hex_code: str):
        self.item_id = item_id
        self.item_uuid = item_uuid
        self.hex_code = hex_code


def find_closest_skyblock_piece(piece: SeymourPiece, length: int = 1, new_method: bool = True):
    lab1 = color.hex_to_lab(piece.hex_code)
    closest_list = defaultdict(list)
    for skyblock_item, color_data in {**default_hexes[piece.item_id], **default_hexes["OTHER"]}.items():
        if new_method:
            similarity = color.compare_delta_e_2000(lab1, color_data['lab'])
        else:
            similarity = color.compare_delta_cie(lab1, color_data['lab'])
        closest_list[similarity].append(color_data['name'])

    closest_list = [(y, x) for x, y in closest_list.items()]
    closest_list = sorted(closest_list, key=lambda x: x[1])
    crystal_found, fairy_found = False, False
    for data in closest_list:
        pieces, sim = data
        to_remove = []
        for piece in pieces:
            if piece.startswith("Crystal "):
                if crystal_found:
                    to_remove.append(piece)
                crystal_found = True
            elif piece.startswith("Fairy "):
                if fairy_found:
                    to_remove.append(piece)
                fairy_found = True
        for piece in to_remove:
            pieces.remove(piece)
    closest_list = [(', '.join(data[0]), data[1]) for data in closest_list if len(data[0]) > 0]
    return closest_list[0:length]


def create_armor_image(piece: SeymourPiece):
    armor_path = f"a/{piece.item_id.lower()}.png"
    armor_overlay_path = f"a/{piece.item_id.lower()}_overlay.png"
    overlay_color = tuple(int(piece.hex_code[i:i + 2], 16) for i in (0, 2, 4))

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
        self.owner = owner_uuid
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

    def insert_item(self, piece: SeymourPieceWithOwnership):
        with self.con:
            self.con.execute("INSERT INTO seymour_pieces VALUES (?, ?, ?, ?, ?, ?)",
                             (piece.piece.item_id, piece.piece.item_uuid, piece.owner,
                              piece.location, piece.last_seen, piece.piece.hex_code))

    def insert_items(self, pieces: dict[str, SeymourPieceWithOwnership]):
        with self.con:
            for piece in pieces.values():
                self.con.execute("INSERT INTO seymour_pieces VALUES (?, ?, ?, ?, ?, ?)",
                                 (piece.piece.item_id, piece.piece.item_uuid, piece.owner,
                                  piece.location, piece.last_seen, piece.piece.hex_code))

    def update_item(self, piece: SeymourPieceWithOwnership):
        with self.con:
            res = self.con.execute('SELECT last_seen FROM seymour_pieces WHERE item_uuid = ?', (piece.piece.item_uuid,))
            current_last_seen = res.fetchone()
            if current_last_seen is None:  # not me checking this one twice
                return
            if piece.last_seen < current_last_seen[0]:
                return

            self.con.execute(
                "UPDATE seymour_pieces SET owner = ?, location = ?, last_seen = ? WHERE item_uuid = ?",
                (piece.owner, piece.location, piece.last_seen, piece.piece.item_uuid)
            )

    def update_items(self, pieces: dict[str, SeymourPieceWithOwnership]):
        with self.con:
            res = self.con.execute(
                f'SELECT item_uuid,last_seen FROM seymour_pieces WHERE item_uuid IN ({",".join(["?"] * len(pieces))})',
                tuple(pieces.keys()))
            for data in res.fetchall():
                current_last_seen = data[1]
                piece = pieces[data[0]]
                if piece.last_seen < current_last_seen:
                    continue
                self.con.execute(
                    "UPDATE seymour_pieces SET owner = ?, location = ?, last_seen = ? WHERE item_uuid = ?",
                    (piece.owner, piece.location, piece.last_seen, piece.piece.item_uuid)
                )

    def add_item_to_db(self, piece: SeymourPieceWithOwnership):
        if self.item_exists(piece.piece.item_uuid):
            self.update_item(piece)
        else:
            self.insert_item(piece)

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
        self.prev_update = 0

    @staticmethod
    def human_format(num):
        num = float('{:.3g}'.format(num))
        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0
        return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])

    @staticmethod
    def custom_item_id(nbt_data):
        try:
            item_id = str(nbt_data['i'][0]['tag']['ExtraAttributes']['id'])
        except Exception as e:
            print("Something went wrong! " + str(e))
            traceback.print_tb(e.__traceback__)
            return "DIRT"

        if item_id not in item_images:
            return "DIRT"
        return item_id

    def send_item_to_webhook(self, auction, nbt_data, reason, extra_data=None):
        webhook_name = "bs"
        try:
            seller_ign, _ = get_name_and_uuid(input_uuid=auction['auctioneer'])
        except KeyError:
            seller_ign = "Unknown"

        embed = DiscordEmbed(title=auction['item_name'], url=f"https://sky.coflnet.com/auction/{auction['uuid']}", description=f"reason for sending: {reason}", color="00FFFF")
        embed.set_author(name=seller_ign, icon_url=f"https://crafatar.com/renders/head/{auction['auctioneer']}")
        embed.set_thumbnail(url=item_images[self.custom_item_id(nbt_data)])
        embed.add_embed_field(name="Price" if auction['bin'] else "Starting Bid", value=self.human_format(auction['starting_bid']), inline=True)
        if reason == "glitched timestamp" or reason == "cool kid salmon hat" or "item??" in reason:
            embed.add_embed_field(name="Museum Date", value=f"<t:{self.timestamp_to_museum_unix(nbt_data['i'][0]['tag']['ExtraAttributes'].get('timestamp'))[0]}>", inline=True)
        if reason == "cheapskate midas":
            embed.add_embed_field(name="Price Paid", value=self.human_format(nbt_data['i'][0]['tag']['ExtraAttributes']['winning_bid']), inline=True)
        if "item??" in reason:
            webhook_name = "museum"
            embed.set_description("")
            embed.add_embed_field(name="iTEM Est. Pos", value=str(extra_data), inline=True)
        embed.set_footer(text=f"/viewauction {auction['uuid']}")
        if "epic exotic" in reason:
            webhook_name = "exotic"
            embed.set_description("")
            embed.add_embed_field(name="Exotic Type", value=str(extra_data), inline=True)
            hex_code = hex(nbt_data["i"][0]["tag"]["display"].get("color", 10511680))
            hex_code = hex_code.replace("0x", "").upper().rjust(6, "0")
            armor_type = {298: "VELVET_TOP_HAT", 299: "CASHMERE_JACKET", 300: "SATIN_TROUSERS", 301: "OXFORD_SHOES"}[nbt_data['i'][0]['id']]
            piece_image = create_armor_image(SeymourPiece(armor_type, "", hex_code))
            piece_image.save("a/armor_piece.png")
            embed.set_thumbnail(url="attachment://armor_image.png")
            embed.add_embed_field(name="Hex", value="#" + hex_code, inline=True)
            send_to_webhook(webhook_name=webhook_name, embed=embed, file_path="a/armor_piece.png")
            return
        send_to_webhook(webhook_name=webhook_name, embed=embed)

    def build_seymour_embed(self, seymour_piece: SeymourPiece, auction):
        closest_list = find_closest_skyblock_piece(seymour_piece, length=3)

        content = ""
        if closest_list[0][1] < 1.0:
            content = "<@&1103413230682001479> "

        closest_list_printable = []
        for closest_item in closest_list:
            string = closest_item[0] + " - "
            if closest_item[1] < 1:
                string += "Matching"
            elif closest_item[1] < 2:
                string += "Very Close"
            elif closest_item[1] < 4:
                string += "Similar"
            elif closest_item[1] < 8:
                string += "Noticeable"
            else:
                string += "Different"
            string += f" ({round(closest_item[1], 2)})"
            closest_list_printable.append(string)

        seller_ign, _ = get_name_and_uuid(input_uuid=auction['auctioneer'])
        print(f"[{datetime.now().strftime('%X')}] "
              f"Seymour Piece Found! Seller: {seller_ign}, "
              f"Piece: {(seymour_piece.item_id, seymour_piece.item_uuid, seymour_piece.hex_code)}")

        piece_image = create_armor_image(seymour_piece)
        piece_image.save("a/armor_piece.png")

        embed = DiscordEmbed(title=auction['item_name'], url=f"https://sky.coflnet.com/auction/{auction['uuid']}", color=seymour_piece.hex_code)
        embed.set_author(name=seller_ign, icon_url=f"https://crafatar.com/renders/head/{auction['auctioneer']}")
        embed.set_thumbnail(url="attachment://armor_image.png")
        embed.add_embed_field(name="Hex", value=f"#{seymour_piece.hex_code}", inline=True)
        embed.add_embed_field(name="Price" if auction['bin'] else "Starting Bid", value=self.human_format(auction['starting_bid']), inline=True)
        embed.add_embed_field(name="Closest Armor Pieces", value="\n".join(closest_list_printable), inline=False)
        embed.set_footer(text=f"/viewauction {auction['uuid']}")

        dupes = self.find_dupes(seymour_piece.hex_code, seymour_piece.item_uuid)
        if len(dupes):
            dupes_joined = f"{len(dupes)} match(es) found!"
            for dupe in dupes:
                dupes_joined += dupe
            embed.set_description(dupes_joined)

        send_to_webhook(webhook_name="seymour", content=content, embed=embed, file_path="a/armor_piece.png")

    def find_dupes(self, hex_code, item_uuid):
        dupes = self.db.matching_hexes(hex_code, item_uuid)
        if dupes is None or not len(dupes):
            return []
        print(f"{len(dupes)} match(es) found!")

        scanner = PlayerScanner()
        printable_dupes = []
        for dupe in dupes:
            try:
                seymour_list = scanner.get_profile(dupe[2], use_i_tem=True)
                scanner.process_seymour_list(seymour_list, dupe[2], sort_by_closest=False)  # add findings to db
                if dupe[1] in seymour_list:
                    owner_ign, _ = get_name_and_uuid(input_uuid=dupe[2])
                    printable_dupes.append(f"\n{dupe[0].replace('_', ' ').title()} last owned by {owner_ign}")
                    print(f"Last Known Owner: {owner_ign}, Piece: {dupe}")
                    continue

                item_info = get_json(f"https://api.tem.cx/items/{dupe[1]}")
                if not item_info['success']:
                    owner_ign, _ = get_name_and_uuid(input_uuid=dupe[2])
                    printable_dupes.append(f"\n{dupe[0].replace('_', ' ').title()} last owned by {owner_ign}")
                    print(f"Last Known Owner: {owner_ign}, Piece: {dupe}")
                    continue
                item_info = item_info['item']
                if item_info['lastChecked'] > dupe[4]:  # given the previous lot failed, this will always be true... but eh
                    piece = SeymourPieceWithOwnership(SeymourPiece(item_info['itemId'], item_info['_id'],
                                                      item_info['colour']), item_info['currentOwner']['playerUuid'],
                                                      item_info['location'].replace("backpack-", "backpack_contents_"), int(item_info['lastChecked'] / 1000))
                    self.db.add_item_to_db(piece)
                    owner_ign, _ = get_name_and_uuid(input_uuid=item_info['currentOwner']['playerUuid'])
                    printable_dupes.append(f"\n{item_info['itemId'].replace('_', ' ').title()} last owned by {owner_ign}")  # this handles transmutation YEP (3 days later i forgot what this joke means)
                    print(f"Last Known Owner: {owner_ign}, Piece: {piece}")
            except Exception as e:
                print(e)
                traceback.print_tb(e.__traceback__)
        return printable_dupes

    @staticmethod
    def get_nbt_data(item_bytes):
        nbt_data = nbt.read_from_nbt_file(file=BytesIO(b64decode(item_bytes)))
        return nbt_data.json_obj(full_json=False)

    @staticmethod
    def timestamp_to_museum_unix(timestamp, use_dst: bool = True):
        if ":" not in timestamp:
            unix_timestamp = int(timestamp) / 1000
            if use_dst:
                unix_timestamp -= 3600  # All Unix timestamps were created on June 11th/12th, no need to DST check!
            return int(unix_timestamp), True
        elif "AM" not in timestamp and "PM" not in timestamp:
            glitched = True
            month, day, year = list(map(int, timestamp[0:8].split("/")))
            year += 2000

            while month > 12:
                month -= 12
                year += 1

            # actual_date = datetime.strptime(timestamp, "%d/%m/%y %H:%M")
            museum_date = datetime.strptime(f"{month}/{day}/{year} {timestamp[9:]}", "%m/%d/%Y %H:%M")
        else:
            glitched = False
            museum_date = datetime.strptime(timestamp, "%m/%d/%y %I:%M %p")

        if use_dst:
            fuck_hypixel = timezone('US/Eastern').localize(museum_date).dst() != timedelta(0)
            if fuck_hypixel:
                museum_date -= timedelta(hours=1)

        return int(museum_date.timestamp()), glitched

    def museum_bullshit(self, museum_queue):
        i_tem_scan_queue = {"items": []}
        for item in museum_queue.copy():
            item_id = item['item_id'].replace("STARRED_", "")
            item_timestamp = item['timestamp']

            if item_id not in oldest_items:
                museum_queue.remove(item)
                continue

            if "first_four_digit" in oldest_items[item_id]:
                if oldest_items[item_id]["first_four_digit"]["timestamp"] <= item_timestamp:
                    museum_queue.remove(item)
                    continue

            item_dict = {"itemId": item_id, "creation": item_timestamp * 1000}
            print(item_dict)
            i_tem_scan_queue['items'].append(item_dict)
            if item_id in ["STONE_BLADE", "ADAPTIVE_BOOTS", "ADAPTIVE_CHESTPLATE", "ADAPTIVE_HELMET", "ADAPTIVE_LEGGINGS", "BONZO_MASK", "BONZO_STAFF", "LAST_BREATH", "SHADOW_ASSASSIN_BOOTS", "SHADOW_ASSASSIN_CHESTPLATE", "SHADOW_ASSASSIN_HELMET", "SHADOW_ASSASSIN_LEGGINGS", "SHADOW_FURY", "SPIDER_QUEENS_STINGER", "VENOMS_TOUCH", "SPIRIT_MASK", "THORNS_BOOTS", "BAT_WAND", "ITEM_SPIRIT_BOW", "BONE_BOOMERANG", "FELTHORN_REAPER"]:
                item_dict = {"itemId": f"STARRED_{item_id}", "creation": item_timestamp * 1000}
                i_tem_scan_queue['items'].append(item_dict)
            elif "STARRED_" in item_id:
                item_dict = {"itemId": item_id.replace("STARRED_", ""), "creation": item_timestamp * 1000}
                i_tem_scan_queue['items'].append(item_dict)

        if not len(i_tem_scan_queue['items']):
            return

        post_data = json.dumps(i_tem_scan_queue)
        i_tem_resp = requests.post(url="https://api.tem.cx/items/position", data=post_data)
        position_data = i_tem_resp.json()
        formatted_data = {}
        for item in position_data['positions']:
            if item['itemId'] in formatted_data:
                if item['creation'] in formatted_data[item['itemId']]:
                    continue
                formatted_data[item['itemId']][item['creation']] = item['highest']
                continue
            formatted_data[item['itemId']] = {}
            formatted_data[item['itemId']][item['creation']] = item['highest']

        print(formatted_data)

        for item in museum_queue:
            item_id = item['item_id'].replace("STARRED_", "")

            try:
                position = formatted_data[item_id][item['timestamp'] * 1000]
            except KeyError:
                print(item)
                continue
            if item_id in ["STONE_BLADE", "ADAPTIVE_BOOTS", "ADAPTIVE_CHESTPLATE", "ADAPTIVE_HELMET", "ADAPTIVE_LEGGINGS", "BONZO_MASK", "BONZO_STAFF", "LAST_BREATH", "SHADOW_ASSASSIN_BOOTS", "SHADOW_ASSASSIN_CHESTPLATE", "SHADOW_ASSASSIN_HELMET", "SHADOW_ASSASSIN_LEGGINGS", "SHADOW_FURY", "SPIDER_QUEENS_STINGER", "VENOMS_TOUCH", "SPIRIT_MASK", "THORNS_BOOTS", "BAT_WAND", "ITEM_SPIRIT_BOW", "BONE_BOOMERANG", "FELTHORN_REAPER"]:
                position += formatted_data[f"STARRED_{item_id}"][item['timestamp'] * 1000]
                position -= 1

            if item['timestamp'] < oldest_items[item_id]["first"]['timestamp']:
                oldest_items[item_id]["first"] = {"edition": position, "timestamp": item['timestamp']}
                print(f"New Oldest {item_id} Found! edition: {position}, timestamp: {item['timestamp']}")
            if position > 1000:
                oldest_items[item_id]["first_four_digit"] = {"edition": position, "timestamp": item['timestamp']}
                continue
            if item['timestamp'] - oldest_items[item_id]["first"]['timestamp'] > 2419200:  # 28 days
                print(f"Unsent {item_id}! edition: {position}, timestamp: {item['timestamp']}, auc id: {item['auction']['uuid']}")
                continue
            self.send_item_to_webhook(item['auction'], item['item_nbt'], "maybe good museum item??", position)

    def find_items(self, auction_page):
        if len(auction_page['auctions']) == 0:
            print(f"Empty auctions page: {json.dumps(auction_page, indent=4)}")
            return
        museum_queue = []
        filtered_auctions = [auc for auc in auction_page['auctions'] if auc['start'] > self.prev_update and not auc['claimed']]
        for auction in filtered_auctions:
            try:
                nbt_data = self.get_nbt_data(auction['item_bytes'])
            except ValueError:
                continue

            attributes = nbt_data["i"][0]["tag"].get("ExtraAttributes")
            if not attributes:
                continue

            item_id = attributes["id"]
            match item_id:
                case 'VELVET_TOP_HAT' | "CASHMERE_JACKET" | "SATIN_TROUSERS" | "OXFORD_SHOES":
                    seymour_piece = SeymourPiece(item_id, attributes['uuid'], hex(nbt_data["i"][0]["tag"]["display"]["color"]).replace("0x", "").upper().rjust(6, '0'))
                    self.build_seymour_embed(seymour_piece, auction)
                    ownership = SeymourPieceWithOwnership(seymour_piece, auction['auctioneer'], "auction_house", int(auction['start'] / 1000))
                    self.db.add_item_to_db(ownership)
                case 'PARTY_HAT_CRAB' | 'PARTY_HAT_CRAB_ANIMATED':
                    year_created = attributes.get("party_hat_year")
                    if year_created and str(year_created) in ("2021", "2023"):
                        self.send_item_to_webhook(auction, nbt_data, "2023 crab hat")
                case 'REINFORCED_IRON_ARROW' | 'GOLD_TIPPED_ARROW' | 'REDSTONE_TIPPED_ARROW' | 'EMERALD_TIPPED_ARROW' | 'BOUNCY_ARROW' | 'ICY_ARROW' | 'ARMORSHRED_ARROW' | 'EXPLOSIVE_ARROW' | 'GLUE_ARROW' | 'NANSORB_ARROW':
                    self.send_item_to_webhook(auction, nbt_data, "funny jax arrow")
                case 'SALMON_HAT':
                    if "raffle_win" not in attributes:
                        self.send_item_to_webhook(auction, nbt_data, "cool kid salmon hat")
                case 'MIDAS_SWORD' | 'MIDAS_STAFF':
                    if "winning_bid" in attributes:
                        if attributes['winning_bid'] < 1000000:
                            self.send_item_to_webhook(auction, nbt_data, "cheapskate midas")
                    else:
                        self.send_item_to_webhook(auction, nbt_data, "no bid midas gaming")

            if item_id in DUNGEON_ITEM_LIST:
                if "baseStatBoostPercentage" not in attributes:
                    if "item_tier" not in attributes:
                        self.send_item_to_webhook(auction, nbt_data, "clean dungeons drop")
                    else:
                        self.send_item_to_webhook(auction, nbt_data, "0% dungeons drop")

            reforge = attributes.get("modifier")
            if reforge and str(reforge) in OG_REFORGE_LIST and auction['category'] != "accessories":
                self.send_item_to_webhook(auction, nbt_data, f"{reforge} reforge")

            origin_tag = attributes.get("originTag")
            if origin_tag and str(origin_tag) in ["ITEM_MENU", "ITEM_COMMAND"]:
                self.send_item_to_webhook(auction, nbt_data, "admin-spawned item")

            item_timestamp = attributes.get("timestamp")
            if item_timestamp:
                unix_timestamp, glitched = self.timestamp_to_museum_unix(str(item_timestamp), use_dst=False)
                if glitched:
                    print(f"[{datetime.now().strftime('%X')}] Glitched Timestamp Found!", auction)
                    self.send_item_to_webhook(auction, nbt_data, "glitched timestamp")
                museum_queue.append({"item_nbt": nbt_data, "auction": auction, "item_id": item_id, "timestamp": unix_timestamp})

            minecraft_id = nbt_data["i"][0]["id"]
            if minecraft_id in (298, 299, 300, 301):
                exotic_type = exotics.get_exotic_type(nbt_data)
                if exotic_type != "DEFAULT":
                    self.send_item_to_webhook(auction, nbt_data, "epic exotic", exotic_type)

        self.museum_bullshit(museum_queue)
        with open("museum_info.json", "w") as museum_file:
            json.dump(oldest_items, museum_file, indent=2)

    def first_check(self, total_pages):
        for i in range(total_pages):
            c = get_json(f"https://api.hypixel.net/skyblock/auctions?page={i}")
            s = time.time_ns()
            for auction in c['auctions']:
                try:
                    nbt_data = self.get_nbt_data(auction['item_bytes'])
                except ValueError:
                    continue

                item_id = str(nbt_data["i"][0]["tag"]["ExtraAttributes"]["id"])
                item_timestamp = nbt_data["i"][0]["tag"]["ExtraAttributes"].get("timestamp")
                if item_timestamp is None:
                    continue

                unix_timestamp = self.timestamp_to_museum_unix(item_timestamp, use_dst=False)[0]
                if item_id in oldest_items:
                    if unix_timestamp < oldest_items[item_id]['oldest']:
                        oldest_items[item_id]['oldest'] = unix_timestamp
                else:
                    oldest_items[item_id] = {}
                    oldest_items[item_id]['oldest'] = unix_timestamp
            print(f"Page {i} completed in {(time.time_ns() - s) / 1e6}ms")
        print(oldest_items)

    def scan_auctions_loop(self):
        c = get_json(f"https://api.hypixel.net/skyblock/auctions?page=0")
        self.prev_update = c['lastUpdated']
        # total_pages = c['totalPages']
        # self.first_check(total_pages)
        while True:
            download_start = time.time_ns()
            auction_api = get_json(f"https://api.hypixel.net/skyblock/auctions?page=0")
            if auction_api is None:
                time.sleep(0.5)
                continue
            download_end = time.time_ns()

            if self.prev_update == auction_api['lastUpdated']:
                time.sleep(0.5)
                continue

            find_start = time.time_ns()
            self.find_items(auction_api)
            find_end = time.time_ns()
            self.prev_update = auction_api['lastUpdated']
            print(f"[{datetime.now().strftime('%X')}] Refresh completed! "
                  f"Download: {(download_end - download_start) / 1e6}ms | "
                  f"Processing: {(find_end - find_start) / 1e6}ms")
            print(f"[{datetime.now().strftime('%X')}] "
                  f"Sleeping for {int(60 - (time.time() - (self.prev_update / 1000)))} seconds...")
            time.sleep(max(int(60 - (time.time() - (self.prev_update / 1000))), 1))


class PlayerScanner:
    def get_profile(self, uuid, use_i_tem=True):
        s = time.time_ns()
        player = get_json(f"https://api.hypixel.net/skyblock/profiles?uuid={uuid}&key={config.api_key}")
        if player is None:
            return {}
        if player.get('profiles') is None:
            return {}
        print(f"Download from Hypixel {(time.time_ns() - s) / 1e6}ms")

        seymour_list = {}
        s = time.time_ns()
        for profile in player['profiles']:
            if uuid not in profile['members']:
                continue
            for menu in ["inv_contents", "inv_armor", "wardrobe_contents", "ender_chest_contents",
                         "backpack_contents", "personal_vault_contents"]:
                if menu == "backpack_contents":
                    backpacks = profile['members'][uuid].get(menu)
                    if backpacks is None:
                        continue
                    for i, backpack in backpacks.items():
                        inventory = self.get_inventory(backpack, f"{menu}_{i}")
                        if inventory is not None:
                            inventory.update(seymour_list)
                            seymour_list = inventory
                else:
                    inventory_bytes = profile['members'][uuid].get(menu)
                    if inventory_bytes is None:
                        continue
                    inventory = self.get_inventory(inventory_bytes, menu)
                    if inventory is not None:
                        inventory.update(seymour_list)
                        seymour_list = inventory
        print(f"Process Hypixel data {(time.time_ns() - s) / 1e6}ms")
        if use_i_tem:
            inventory = self.get_i_tem_data(uuid=uuid)
            if inventory is not None:
                inventory.update(seymour_list)
                seymour_list = inventory
        return seymour_list

    @staticmethod
    def get_inventory(inventory, inventory_name):
        seymour_list = {}
        if inventory.get('data') is None:
            return {}
        try:
            decoded = nbt.read_from_nbt_file(file=BytesIO(b64decode(inventory['data'])))
        except Exception as e:
            print("Something went wrong! " + str(e))
            print(inventory_name)
            return {}
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

            seymour_list[str(item['ExtraAttributes'].get('uuid', "NONE"))] = {
                "item_id": str(item['ExtraAttributes']['id']),
                "uuid": str(item['ExtraAttributes'].get('uuid', "NONE")),
                "last_seen": int(time.time()),
                "location": inventory_name,
                "hex": hex_code
            }
        return seymour_list

    @staticmethod
    def get_i_tem_data(uuid):
        seymour_list = {}
        url = f"https://api.tem.cx/items/player/{uuid}"
        s = time.time_ns()

        i_item_list = get_json(url)
        if i_item_list is None:
            return {}

        print(f"Download from iTEM {(time.time_ns() - s) / 1e6}ms")

        s = time.time_ns()

        for item in i_item_list['items']:
            if item['itemId'] not in ("VELVET_TOP_HAT", "CASHMERE_JACKET", "SATIN_TROUSERS", "OXFORD_SHOES"):
                continue
            seymour_list[item['_id']] = {
                "item_id": item['itemId'],
                "uuid": item['_id'],
                "last_seen": int(item['lastChecked'] / 1000),
                "location": item['location'].replace("backpack-", "backpack_contents_"),
                "hex": item['colour']
            }
            return seymour_list
        print(f"Process iTEM data {(time.time_ns() - s) / 1e6}ms")

    @staticmethod
    def process_seymour_list(seymour_list, uuid, sort_by_closest=True):
        # SLOW
        db = SeymourDatabase()
        pieces = []
        for item in seymour_list.values():
            seymour_piece = SeymourPiece(item['item_id'], item['uuid'], item['hex'])
            ownership_piece = SeymourPieceWithOwnership(seymour_piece, uuid, item['location'], item['last_seen'])
            pieces.append(ownership_piece)

            if not sort_by_closest:
                continue
            closest_item = find_closest_skyblock_piece(seymour_piece, length=1)[0]
            item['closest'] = closest_item

        sorted_list = list(seymour_list.values())
        if sort_by_closest:
            sorted_list = sorted(list(seymour_list.values()), key=lambda x: x['closest'][1])

        db.add_items_to_db(pieces)

        return sorted_list


@bot.event
async def on_ready():
    await bot.change_presence(
        activity=disnake.Activity(
            type=disnake.ActivityType.playing,
            name="with Hex Codes"
        )
    )

    print(f"[{datetime.now().strftime('%X')}] Connected to bot: {bot.user.name}")
    print(f"[{datetime.now().strftime('%X')}] Bot ID: {bot.user.id}")


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
            choices={"Helmet": "VELVET_TOP_HAT", "Chestplate": "CASHMERE_JACKET", "Leggings": "SATIN_TROUSERS", "Boots": "OXFORD_SHOES"}
        ),
        new_method: bool = True
):
    await inter.response.defer()
    seymour_piece = SeymourPiece(armor_type, "", hex_code)
    closest_list = find_closest_skyblock_piece(seymour_piece, length=3, new_method=new_method)

    piece = create_armor_image(seymour_piece)
    piece.save("a/armor_piece.png")

    embed = disnake.Embed(
        title=f"Closest SkyBlock pieces to hex code #{hex_code.upper()}:",
        description=f"{closest_list[0][0]}: {round(closest_list[0][1], 2)}\n"
                    f"{closest_list[1][0]}: {round(closest_list[1][1], 2)}\n"
                    f"{closest_list[2][0]}: {round(closest_list[2][1], 2)}",
        colour=int(hex_code, 16)
    )
    embed.set_thumbnail(file=disnake.File("a/armor_piece.png"))
    await inter.edit_original_message(embed=embed)


@bot.slash_command(
    name="earliest_known",
    description="returns the timestamp for the earliest known item",
    dm_permission=False
)
async def earliest_known(inter: disnake.AppCommandInteraction, item_id: str):
    await inter.response.defer()
    if item_id not in oldest_items:
        await inter.edit_original_message("unknown item id, please check your spelling and try again. newer/non-museumable items may not be supported.")
        return
    await inter.edit_original_message(embed=disnake.Embed(title=item_id, description=f"the oldest {item_id} i've seen was created on <t:{oldest_items[item_id]['first']['timestamp']}> (<t:{oldest_items[item_id]['first']['timestamp']}:R>), and is estimated to be position {oldest_items[item_id]['first']['edition']}"))


@bot.slash_command(
    name="skyblock_time",
    description="Shows the current calendar date in SkyBlock",
    dm_permission=False
)
async def estimate_skyblock_time(inter: disnake.AppCommandInteraction):
    current_epoch = int(time.time())
    skyblock_epoch = current_epoch - 1560275700

    skyblock_year = int(skyblock_epoch / 446400)
    skyblock_month = int((skyblock_epoch / 37200) - (skyblock_year * 12))
    skyblock_day = int((skyblock_epoch / 1200) - (skyblock_year * 372) - (skyblock_month * 31))

    display_month = ["Spring", "Summer", "Autumn", "Winter"][int(skyblock_month/3)]
    if skyblock_month % 3 == 0:
        display_month = "Early " + display_month
    elif skyblock_month % 3 == 2:
        display_month = "Late " + display_month

    await inter.response.send_message(f"It is currently {display_month} {skyblock_day + 1} of SkyBlock Year {skyblock_year + 1}")


@bot.slash_command(
    name="find_closest_hex",
    description="does absolutely nothing!",
    dm_permission=False
)
@commands.has_role('dw about it')
async def find_closest_hex(inter: disnake.AppCommandInteraction, hex_code: str, item_id=None, owner=None, new_method: bool = True):
    await inter.response.defer()
    dupes_con = sqlite3.connect("seymour_pieces.db")
    dupes_cur = dupes_con.cursor()

    uuid = ""
    if owner:
        name, uuid = get_name_and_uuid(input_name=owner)

    res = dupes_cur.execute("SELECT item_uuid,hex_code FROM seymour_pieces")
    all_hexes = res.fetchall()
    if all_hexes is None:
        await inter.edit_original_message("it broke")
        return

    item_dict = {}
    lab1 = color.hex_to_lab(hex_code)
    for item in all_hexes:
        lab2 = color.hex_to_lab(item[1])
        if new_method:
            similarity = color.compare_delta_e_2000(lab1, lab2)
        else:
            similarity = color.compare_delta_cie(lab1, lab2)
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
        if owner and uuid != item[2]:
            good_items.remove(item)
            item_dict.pop(item[1])
            continue
        item_with_sim = item + (item_dict[item[1]],)
        item_dict[item[1]] = list(item_with_sim)

    item_dict = sorted(list(item_dict.values()), key=lambda x: x[-1])
    if not item_id:
        sorted_item_dict = {"Velvet Top Hat": [x for x in item_dict if x[0] == "VELVET_TOP_HAT"],
                            "Cashmere Jacket": [x for x in item_dict if x[0] == "CASHMERE_JACKET"],
                            "Satin Trousers": [x for x in item_dict if x[0] == "SATIN_TROUSERS"],
                            "Oxford Shoes": [x for x in item_dict if x[0] == "OXFORD_SHOES"]}
        resp_string = ""
        for armor_type, items in sorted_item_dict.items():
            resp_string += armor_type + '\n'
            for count, item in enumerate(items[0:5]):
                name, _ = get_name_and_uuid(item[2])
                temp = f"`{item[5]}` ({round(item[6], 2)}): {name}'s `{item[3]}` <t:{item[4]}:R>"
                if count == 0:
                    temp += f" ({item[1]})"
                resp_string += temp + '\n'
    else:
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
            res = dupes_db.con.execute("SELECT t.* FROM seymour_pieces t JOIN (SELECT hex_code FROM seymour_pieces GROUP BY hex_code HAVING COUNT(*) > 2 ) d ON t.hex_code = d.hex_code")
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
    name="query",
    description="dw about it",
    dm_permission=False
)
async def query(inter: disnake.AppCommandInteraction, db_query, params, length: int = 3, hidden: bool = False):
    await inter.response.defer(ephemeral=hidden)
    dupes_con = sqlite3.connect("seymour_pieces.db")
    dupes_cur = dupes_con.cursor()

    res = dupes_cur.execute(db_query, (params,))
    duplicates = res.fetchall()
    if duplicates is None:
        await inter.edit_original_message("you used it wrong go away")
        return

    reply_message = ""
    for item in duplicates[0:min(length, len(duplicates))]:
        reply_message += str(item) + "\n"

    await inter.edit_original_message(reply_message)


@bot.slash_command(
    name="check_poifect",
    description="does absolutely nothing!",
    dm_permission=False
)
@commands.default_member_permissions(administrator=True)
async def check_perfect(inter: disnake.AppCommandInteraction):
    await inter.response.defer()
    hex_list_with_piece = {}
    hex_list = []
    for armor_type, armor_data in default_hexes:
        hex_list_with_piece[armor_type] = {y['hex'] for x, y in armor_data.items()}
        hex_list += {y['hex'] for x, y in armor_data.items()}
    perfect_db = SeymourDatabase()
    with perfect_db.con:
        res = perfect_db.con.execute(
            f"SELECT * FROM seymour_pieces WHERE hex_code IN ({','.join(['?'] * len(hex_list))})", tuple(hex_list))
        perfects = res.fetchall()
        if perfects is None:
            await inter.edit_original_message("none found")
            return

        printable = ""
        for item in perfects:
            if item[-1] not in hex_list_with_piece[item[0]]:
                continue
            printable += item + "\n"

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
    name, uuid = get_name_and_uuid(input_name=input_name)
    print(f"Get UUID from name {(time.time_ns() - s) / 1e6}ms")

    scanner = PlayerScanner()
    seymour_list = scanner.get_profile(uuid, use_i_tem=include_item)

    s = time.time_ns()
    seymour_list = scanner.process_seymour_list(seymour_list, uuid)

    print(f"Process Seymour list {(time.time_ns() - s) / 1e6}ms")

    s = time.time_ns()
    if not len(seymour_list):
        await inter.edit_original_message(f"{name} has no known Seymour pieces.")
        return
    response_string = f"```{name}'s total pieces: {len(seymour_list)}```"

    for i in range(min(len(seymour_list), length)):
        response_string += f"`{seymour_list[i]['item_id'].replace('_', ' ').title()}` in `{seymour_list[i]['location']}`," \
                           f" `#{seymour_list[i]['hex']}`, closest: `{seymour_list[i]['closest'][0].replace('_', ' ').title()} - {round(seymour_list[i]['closest'][1], 2)}`\n"
    print(f"Made response {(time.time_ns() - s) / 1e6}ms")
    s = time.time_ns()
    await inter.edit_original_message(response_string)
    print(f"Edit message {(time.time_ns() - s) / 1e6}ms")


@bot.slash_command(
    name="stab_seymour",
    description="stabs seymour",
    dm_permission=False
)
async def stab_seymour(inter: disnake.AppCommandInteraction):
    await inter.response.defer()
    with open("museum_info.json", "w") as museum_file:
        json.dump(oldest_items, museum_file, indent=2)
    await inter.edit_original_message("i am now dead, o7")
    exit(69)


def main():
    # with open("OXFORD_SHOES_0-81765.csv", "r") as csv_file:
    #     csv_dict = csv.DictReader(csv_file)
    #     line_count = 0
    #     item_id = "OXFORD_SHOES"

    #     seymour_list = []

    #     for row in csv_dict:
    #         if line_count == 0:
    #             print(f"Column names are {', '.join(list(row.keys())[:-1])}")
    #             line_count += 1
    #             continue

    #         item_hex_code = hex(int(row['colour'])).replace("0x", "").rjust(6, "0")
    #         owner = row['currentOwner.playerUuid']
    #         uuid = row['ï»¿_id']
    #         datetime_obj = datetime.datetime.strptime(row['lastChecked'], "%a %b %d %H:%M:%S UTC %Y")
    #         timestamp = datetime_obj.replace(tzinfo=datetime.timezone.utc).timestamp()
    #         location = row['location'].replace("backpack-", "backpack_contents_")

    #         seymour_piece = SeymourPieceWithOwnership(SeymourPiece(item_id, uuid, item_hex_code.upper()), owner, location, int(timestamp))
    #         seymour_list.append(seymour_piece)
    #         line_count += 1

    # seymour_db = SeymourDatabase()
    # count = 0
    # while count < len(seymour_list):
    #     abbr_list = seymour_list[count:min(count+1000, len(seymour_list))]
    #     seymour_db.add_items_to_db(abbr_list)
    #     print(f"at {count+1000} items")
    #     count += 1000

    # print(len(seymour_list))

    # # seymour_db.add_items_to_db(seymour_list)
    # exit()
    finder = AuctionThread()
    finder.start()

    print(f"[{datetime.now().strftime('%X')}] Auction Tracking Started")

    bot.run(config.bot_token)


if __name__ == '__main__':
    main()
