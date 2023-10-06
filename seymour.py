import disnake
from datetime import datetime
from disnake.ext import commands

import color
import config

bot = commands.InteractionBot()
bot.run(config.bot_token)


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
            for item in items[0:5]:
                name, _ = get_name_and_uuid(item[2])
                temp = f"`{item[5]}` ({round(item[6], 2)}): {name}'s `{item[3]}` <t:{item[4]}:R>"
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