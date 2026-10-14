"""Photos used on the site, with the credit each licence requires.

All images come from Wikimedia Commons under Creative Commons licences. They were
resized (and, for the two Tim Buss shots, cropped to remove the photographer's
watermark), so each credit says "cropped and resized" — BY-SA asks for that to be
marked. `pos` is the CSS object-position that keeps the subject in frame when the
photo is cropped to a wide hero banner.
"""

_BY = ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/")
_BY_SA_3 = ("CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/")
_BY_SA_4 = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")

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
}

# The photo behind the home-page hero: the widest, calmest line-up shot.
HERO_SLUG = "swamis"


def photo(slug):
    return PHOTOS.get(slug)


def credit_text(p):
    """Plain-text credit, e.g. 'Mikefairbanks, CC BY-SA 3.0, cropped and resized'."""
    return "%s, %s, cropped and resized" % (p["author"], p["licence"][0])
