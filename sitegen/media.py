"""Photos used on the site, with the credit each licence requires.

All images come from Wikimedia Commons under Creative Commons licences (or in the public
domain). They were resized, and some cropped (the Tim Buss shots to remove the photographer's
watermark, D Street to landscape), so each credit says "cropped and resized": BY-SA asks for
that to be marked. `pos` is the CSS object-position that keeps the subject in frame when the
photo is cropped to a wide hero banner. Every photo also has a small `-sm` copy for the tiles.
Each `source` link is the file's Commons page, which carries the full licence and history.
"""

_BY = ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/")
_BY_SA_2 = ("CC BY-SA 2.0", "https://creativecommons.org/licenses/by-sa/2.0/")
_BY_SA_3 = ("CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/")
_BY_SA_4 = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")
_BY_3 = ("CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/")
_BY_4 = ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")
_CC0 = ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/")
_PD = ("Public domain", "https://creativecommons.org/publicdomain/mark/1.0/")

PHOTOS = {
    "swamis": {
        "file": "swamis.jpg", "w": 1600, "h": 862, "pos": "50% 75%",
        "alt": "Surfers lined up on a clean left at Swami's, seen from the bluff",
        "author": "Mikefairbanks", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:Swami%27s_Surf_Spot_in_Encinitas,_California.jpg",
    },
    "blacks": {
        "file": "blacks.jpg", "w": 1600, "h": 1064, "pos": "50% 80%",
        "alt": "Shore break rolling onto the sand at Black's Beach",
        "author": "Levi Clancy", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Black%27s_Beach,_La_Jolla,_San_Diego,_California_01.jpg",
    },
    "grandview": {
        "file": "grandview.jpg", "w": 1000, "h": 690, "pos": "50% 45%",
        "alt": "Three surfers carrying boards down the beach at Grandview",
        "author": "Tim Buss", "licence": _BY,
        "source": "https://commons.wikimedia.org/wiki/File:Grandview,_Encinitas_(8522175341).jpg",
    },
    "beacons": {
        "file": "beacons.jpg", "w": 1200, "h": 850, "pos": "30% 80%",
        "alt": "A surfer walking past the stairs and sea wall at Beacon's",
        "author": "Tim Buss", "licence": _BY,
        "source": "https://commons.wikimedia.org/wiki/File:Beacons_Beach,_Encinitas_(32753054670).jpg",
    },
    "oceanside": {
        "file": "oceanside.jpg", "w": 1600, "h": 988, "pos": "50% 40%",
        "alt": "Palm trees silhouetted against an orange sunset at Oceanside Harbor",
        "author": "John D.", "licence": _BY,
        "source": "https://commons.wikimedia.org/wiki/File:Sunset_Oceanside_Harbor_(52547236325).jpg",
    },

    # ---- the rest of the county ----
    "oceanside-pier": {
        "file": "oceanside-pier.jpg", "w": 1600, "h": 901, "pos": "50% 55%",
        "alt": "A long pier reaching out over breaking waves at Oceanside, seen from above",
        "author": "Redideo", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Oceanside-Pier-San-Diego-Drone-Photography.jpg",
    },
    "ponto": {
        "file": "ponto.jpg", "w": 1600, "h": 1201, "pos": "50% 68%",
        "alt": "Waves rolling onto the wide beach at South Carlsbad, looking north",
        "author": "Sam Trenholme", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:SouthCarlsbadStateBeach2019.jpg",
    },
    "tamarack": {
        "file": "tamarack.jpg", "w": 1600, "h": 1066, "pos": "50% 55%",
        "alt": "A lifeguard tower on the beach at Tamarack in Carlsbad",
        "author": "Visitor7", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:Tower_33_on_Carlsbad_State_Beach,_CA.jpg",
    },
    "moonlight": {
        "file": "moonlight.jpg", "w": 1000, "h": 700, "pos": "50% 62%",
        "alt": "Foam from a wave sliding up the sand beneath the bluffs at Moonlight Beach",
        "author": "Tim Buss", "licence": _BY,
        "source": "https://commons.wikimedia.org/wiki/File:Moonlight_Beach,_Encinitas_(11162665093).jpg",
    },
    "d-street": {
        "file": "d-street.jpg", "w": 1600, "h": 1066, "pos": "50% 45%",
        "alt": "The D Street viewpoint sign above the ocean in Encinitas",
        "author": "Brovell", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:D_street.jpg",
    },
    "cardiff": {
        "file": "cardiff.jpg", "w": 1600, "h": 1066, "pos": "50% 42%",
        "alt": "Waves breaking over the reef at Cardiff, looking north along the beach",
        "author": "Bovlb", "licence": _PD,
        "source": "https://commons.wikimedia.org/wiki/File:Cardiff_Beach_looking_north.jpg",
    },
    "fletcher-cove": {
        "file": "fletcher-cove.jpg", "w": 1600, "h": 1066, "pos": "50% 55%",
        "alt": "Sandstone bluff above the beach at Fletcher Cove in Solana Beach",
        "author": "rosalynn carmen", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:Fletcher_Cove,_the_cliff_-_panoramio.jpg",
    },
    "del-mar": {
        "file": "del-mar.jpg", "w": 1600, "h": 1200, "pos": "50% 32%",
        "alt": "Sunset over the ocean above the coastal railway at Del Mar",
        "author": "Z3lvs", "licence": _CC0,
        "source": "https://commons.wikimedia.org/wiki/File:Sunset_over_the_Pacific_above_the_coastal_railway,_Del_Mar_Bluffs,_California.jpg",
    },
    "torrey-pines": {
        "file": "torrey-pines.jpg", "w": 1600, "h": 891, "pos": "50% 55%",
        "alt": "Surf and sandstone cliffs at Torrey Pines, seen from above",
        "author": "Redideo", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Drone_Photography_Torrey_Pines_Beach_San_Diego.jpg",
    },
    "scripps-pier": {
        "file": "scripps-pier.jpg", "w": 1600, "h": 893, "pos": "50% 40%",
        "alt": "Scripps Pier stretching over the surf at La Jolla, seen from above",
        "author": "Redideo", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Drone_Photography_UCSD_Scripps_Pier_San_Diego.jpg",
    },
    "la-jolla-shores": {
        "file": "la-jolla-shores.jpg", "w": 1600, "h": 1200, "pos": "50% 50%",
        "alt": "A lifeguard tower on the sand at La Jolla Shores",
        "author": "Avi Richards", "licence": _CC0,
        "source": "https://commons.wikimedia.org/wiki/File:Beach_Sunset_(Unsplash).jpg",
    },
    "windansea": {
        "file": "windansea.jpg", "w": 1600, "h": 1200, "pos": "50% 50%",
        "alt": "A wave exploding against the rocks at Windansea at sunset",
        "author": "Matthew T Rader", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Waves_crashing_on_rocks_at_Windansea_Beach,_San_Diego,_California.jpg",
    },
    "tourmaline": {
        "file": "tourmaline.jpg", "w": 1600, "h": 1200, "pos": "50% 55%",
        "alt": "Sand and a sandstone bluff at Tourmaline Surfing Park",
        "author": "Invertzoo", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:Tourmaline_Surfing_Park,_California.JPG",
    },
    "pacific-beach": {
        "file": "pacific-beach.jpg", "w": 1600, "h": 1200, "pos": "50% 27%",
        "alt": "A surfer silhouetted at sunset on Pacific Beach",
        "author": "SamMiller55A", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Pacific_Beach_Surfer.jpg",
    },
    "mission-beach": {
        "file": "mission-beach.jpg", "w": 1600, "h": 1066, "pos": "50% 40%",
        "alt": "The Giant Dipper roller coaster at Belmont Park, Mission Beach",
        "author": "Visitor7", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:Giant_Dipper_Roller_Coaster-10.jpg",
    },
    "ocean-beach": {
        "file": "ocean-beach.jpg", "w": 1501, "h": 1250, "pos": "50% 55%",
        "alt": "Big surf pounding the pier at Ocean Beach",
        "author": "Bengt Nyman", "licence": _BY_3,
        "source": "https://commons.wikimedia.org/wiki/File:Big_surf_hits_Ocean_Beach,_California_-_panoramio.jpg",
    },
    "sunset-cliffs": {
        "file": "sunset-cliffs.jpg", "w": 1600, "h": 1067, "pos": "50% 55%",
        "alt": "Waves washing against the cliffs at Sunset Cliffs",
        "author": "Saltytog", "licence": _BY_4,
        "source": "https://commons.wikimedia.org/wiki/File:Sunset_Cliffs,_San_Diego.jpg",
    },
    "coronado": {
        "file": "coronado.jpg", "w": 1600, "h": 1200, "pos": "50% 35%",
        "alt": "A lifeguard station silhouetted against the sunset on Coronado beach",
        "author": "Lahti213", "licence": _BY_SA_4,
        "source": "https://commons.wikimedia.org/wiki/File:Coronado_beach_lifeguard_station.jpg",
    },
    "imperial-beach": {
        "file": "imperial-beach.jpg", "w": 1600, "h": 1067, "pos": "50% 65%",
        "alt": "Imperial Beach pier against an orange sunset",
        "author": "Stephen Bay", "licence": _BY_4,
        "source": "https://commons.wikimedia.org/wiki/File:Imperial_Beach_Pier.jpg",
    },
    "tijuana-sloughs": {
        "file": "tijuana-sloughs.jpg", "w": 1600, "h": 945, "pos": "50% 60%",
        "alt": "Surf and a hazy headland at Border Field State Park",
        "author": "Tony Webster", "licence": _BY,
        "source": "https://commons.wikimedia.org/wiki/File:Border_Field_State_Park_-_Imperial_Beach_(15850693647).jpg",
    },
    "pipes": {
        "file": "pipes.jpg", "w": 1600, "h": 1200, "pos": "50% 55%",
        "alt": "The sun setting over the surf at San Elijo State Beach, with two surfers waiting out past the break",
        "author": "Bjorn", "licence": _BY_SA_2,
        "source": "https://commons.wikimedia.org/wiki/File:San_Elijo_State_Beach.jpg",
    },
    "bird-rock": {
        "file": "bird-rock.jpg", "w": 1600, "h": 1066, "pos": "50% 45%",
        "alt": "The Bird Rock coastline, with the reef shelf in the foreground and houses along the bluff",
        "author": "catlin.wolfard", "licence": _BY_SA_3,
        "source": "https://commons.wikimedia.org/wiki/File:So_Cal_-_panoramio_(2).jpg",
    },
    "buccaneer": {
        "file": "buccaneer.jpg", "w": 1600, "h": 929, "pos": "50% 75%",
        "alt": "A surfer sitting in the water as a swell rolls through at sunset in Oceanside",
        "author": "Jason Zook", "licence": _CC0,
        "source": "https://commons.wikimedia.org/wiki/File:Oceanside,_United_States_(Unsplash).jpg",
    },
}

# The photo behind the home-page hero: the widest, calmest line-up shot.
HERO_SLUG = "swamis"


def photo(slug):
    return PHOTOS.get(slug)


TILE_WIDTH = 480


def tile(p):
    """(file, width, height) of the small copy used for the list tiles (`<name>-sm.jpg`, 480 px
    wide), so a 130 px tile doesn't pull a 500 KB photo. Never larger than the original."""
    w = min(TILE_WIDTH, p["w"])
    return p["file"].replace(".jpg", "-sm.jpg"), w, round(w * p["h"] / p["w"])


def credit_text(p):
    """Plain-text credit, e.g. 'Mikefairbanks, CC BY-SA 3.0, cropped and resized'."""
    return "%s, %s, cropped and resized" % (p["author"], p["licence"][0])
