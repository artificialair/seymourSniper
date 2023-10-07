import json

crystal_hexes = ["1F0030", "46085E", "54146E", "5D1C78", "63237D", "6A2C82", "7E4196", "8E51A6", "9C64B3", "A875BD",
                 "B88BC9", "C6A3D4", "D9C1E3", "E5D1ED", "EFE1F5", "FCF3FF"]
fairy_hexes = ["660033", "99004C", "CC0066", "FF007F", "FF3399", "FF66B2", "FF99CC", "FFCCE5"]
og_fairy_hexes = ["660066", "990099", "CC00CC", "FF00FF", "FF33FF", "FF66FF", "FF99FF", "FFCCFF", "E5CCFF", "CC99FF",
                  "B266FF", "9933FF", "7F00FF", "6600CC", "4C0099", "330066"]
og_fairy_ids = {
        "660033": [299, 300, 301],
        "99004C": [300, 301],
        "CC0066": [301],
        "FFCCE5": [298, 299, 300],
        "FF99CC": [298, 299],
        "FF66B2": [298]
}

with open('default_hexes.json', "r") as r:
    default_hexes = json.load(r)


def get_exotic_type(nbt_data):
    if "dye_item" in nbt_data["i"][0]["tag"]["ExtraAttributes"]:
        return "DEFAULT"
    minecraft_id = nbt_data["i"][0]["id"]
    reference = 0
    match minecraft_id:
        case 298:
            reference = "VELVET_TOP_HAT"
        case 299:
            reference = "CASHMERE_JACKET"
        case 300:
            reference = "SATIN_TROUSERS"
        case 301:
            reference = "OXFORD_SHOES"

    item_id = nbt_data["i"][0]["tag"]["ExtraAttributes"]["id"].replace("STARRED_", "")
    if item_id in ("LEATHER_HELMET", "LEATHER_CHESTPLATE", "LEATHER_LEGGINGS", "LEATHER_BOOTS",
                   "CRYSTAL_HELMET", "CRYSTAL_CHESTPLATE", "CRYSTAL_LEGGINGS", "CRYSTAL_BOOTS",
                   "FAIRY_HELMET", "FAIRY_CHESTPLATE", "FAIRY_LEGGINGS", "FAIRY_BOOTS", "GREAT_SPOOK_HELMET",
                   "GREAT_SPOOK_CHESTPLATE", "GREAT_SPOOK_LEGGINGS", "GREAT_SPOOK_BOOTS", "GHOST_BOOTS",
                   "VELVET_TOP_HAT", "CASHMERE_JACKET", "SATIN_TROUSERS", "OXFORD_SHOES"):
        return "DEFAULT"
    if item_id not in default_hexes[reference]:
        print("Unknown Item: " + item_id)
        return "DEFAULT"
    hex_code = hex(nbt_data["i"][0]["tag"]["display"].get("color", 10511680))
    hex_code = hex_code.replace("0x", "").upper().rjust(6, "0")
    if hex_code == default_hexes[reference][item_id]['hex']:
        return "DEFAULT"
    if hex_code == "A06540":
        return "BLEACHED"
    if item_id == "RANCHERS_BOOTS" and hex_code == "CC5500":
        return "DEFAULT"
    if item_id in ["REAPER_CHESTPLATE", "REAPER_LEGGINGS", "REAPER_BOOTS"] and hex_code == "FF0000":
        return "DEFAULT"
    if hex_code in crystal_hexes:
        return "CRYSTAL"
    if hex_code in fairy_hexes:
        if hex_code in og_fairy_ids and minecraft_id in og_fairy_ids[hex_code]:
            return "OG FAIRY"
        return "FAIRY"
    if hex_code in og_fairy_hexes:
        return "OG FAIRY"
    return "EXOTIC"
