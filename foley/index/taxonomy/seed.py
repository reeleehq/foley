"""Seed taxonomy data: curated phrases on real UCS rows, and the AudioSet overlap map.

The default UCS table is the shipped v8.2.1 master (``data/ucs_master.json``; #227,
#237). This seed is two things on top of it:

- **Curated phrases.** Each row names a real master CatID and adds hand-written
  multi-word phrases (``"rain on window"``, ``"door creak"``) that the master's
  single-word synonyms lack; :func:`~foley.index.taxonomy.ucs.load_ucs_table` adds
  them to the master row. ``category``/``subcategory`` are the master's, verbatim
  (a test pins that).
- **The offline fallback.** When the master file is absent, these rows alone are
  the table, so a resolution still lands on a real CatID.

Every CatID here exists in UCS v8.2.1. The pre-master seed used invented ones
(``WEATHRain``, ``GLASBreak``); :data:`LEGACY_CATIDS` says where each one went, so a
record stamped with one still finds its row.
"""

#: The pre-master seed's invented CatIDs -> the real UCS v8.2.1 CatID that replaced
#: each (#237). ``IMPTGeneral`` has none: UCS has no generic impact row.
#: :meth:`~foley.index.taxonomy.model.UcsTable.get` resolves them.
LEGACY_CATIDS: "dict[str, str]" = {
    "WEATHRain": "RAIN",
    "WEATHWind": "WIND",
    "WEATHThunder": "THUN",
    "DOORMetal": "DOORMetl",
    "DOORKnob": "DOORHdwr",
    "FOOTWood": "FEETHmn",
    "FOOTConc": "FEETHmn",
    "FOOTGravel": "FEETHmn",
    "DESTGeneral": "DESTRCrsh",
    "GLASBreak": "GLASBrk",
    "WATRRun": "WATRFlow",
    "WATRSplash": "WATRSplsh",
    "LIQDPour": "WATRPour",
    "FIREGeneral": "FIREBurn",
    "FIREWhoosh": "FIREWhsh",
    "VEHCarInt": "VEHInt",
    "VEHCarExt": "VEHCar",
    "AMBUrban": "AMBUrbn",
    "AMBNature": "AMBForst",
    "GUIBeep": "UIBeep",
    "GUIWhoosh": "UIMvmt",
    "ANMLBird": "BIRDSong",
    "GUNHandgun": "GUNPis",
    "EXPLGeneral": "EXPLReal",
    "CLOTHMove": "CLOTHMvmt",
    "PAPRHandle": "PAPRHndl",
    "MACHGeneral": "MACHMisc",
    "COMMPhone": "COMTelph",
}

#: Curated rows, keyed by real UCS v8.2.1 CatIDs. Each row: catid, category,
#: subcategory (the master's), and extra lowercased phrases.
SEED_UCS_TABLE: list[dict] = [
    {
        "catid": "DOORWood",
        "category": "DOORS",
        "subcategory": "WOOD",
        "synonyms": [
            "wooden door",
            "oak door",
            "door creak",
            "door open",
            "door close",
            "door slam",
        ],
    },
    {
        "catid": "DOORMetl",
        "category": "DOORS",
        "subcategory": "METAL",
        "synonyms": ["metal door", "steel door", "hatch", "cell door"],
    },
    {
        "catid": "DOORHdwr",
        "category": "DOORS",
        "subcategory": "HARDWARE",
        "synonyms": ["doorknob", "door handle", "latch", "handle turn"],
    },
    {
        "catid": "RAIN",
        "category": "RAIN",
        "subcategory": "GENERAL",
        "synonyms": [
            "rain",
            "rainfall",
            "raining",
            "rain on window",
            "downpour",
            "drizzle",
        ],
    },
    {
        "catid": "WIND",
        "category": "WIND",
        "subcategory": "GENERAL",
        "synonyms": ["wind", "gust", "breeze", "howling wind", "windy"],
    },
    {
        "catid": "THUN",
        "category": "WEATHER",
        "subcategory": "THUNDER",
        "synonyms": [
            "thunder",
            "thunderclap",
            "thunderstorm",
            "thunder crack",
            "rumble",
        ],
    },
    {
        "catid": "FEETHmn",
        "category": "FOOTSTEPS",
        "subcategory": "HUMAN",
        "synonyms": [
            "footsteps wood",
            "walking wood floor",
            "footfall wood",
            "footsteps concrete",
            "walking pavement",
            "footsteps sidewalk",
            "footsteps gravel",
            "walking gravel",
            "crunch gravel",
        ],
    },
    {
        "catid": "DESTRCrsh",
        "category": "DESTRUCTION",
        "subcategory": "CRASH & DEBRIS",
        "synonyms": ["destruction", "collapse", "debris", "rubble", "demolition"],
    },
    {
        "catid": "GLASBrk",
        "category": "GLASS",
        "subcategory": "BREAK",
        "synonyms": [
            "glass break",
            "glass shatter",
            "shattering glass",
            "broken glass",
        ],
    },
    {
        "catid": "WATRFlow",
        "category": "WATER",
        "subcategory": "FLOW",
        "synonyms": ["running water", "stream", "faucet", "tap water", "flowing water"],
    },
    {
        "catid": "WATRSplsh",
        "category": "WATER",
        "subcategory": "SPLASH",
        "synonyms": ["splash", "splashing", "water splash", "plop"],
    },
    {
        "catid": "WATRPour",
        "category": "WATER",
        "subcategory": "POUR",
        "synonyms": ["pour", "pouring", "glug", "liquid pour"],
    },
    {
        "catid": "FIREBurn",
        "category": "FIRE",
        "subcategory": "BURNING",
        "synonyms": ["fire", "flames", "campfire", "crackling fire", "burning"],
    },
    {
        "catid": "FIREWhsh",
        "category": "FIRE",
        "subcategory": "WHOOSH",
        "synonyms": ["fire whoosh", "flame burst", "fireball", "ignite whoosh"],
    },
    {
        "catid": "VEHInt",
        "category": "VEHICLES",
        "subcategory": "INTERIOR",
        "synonyms": ["car interior", "in car", "car cabin"],
    },
    {
        "catid": "VEHCar",
        "category": "VEHICLES",
        "subcategory": "CAR",
        "synonyms": ["car pass by", "car exterior", "car drive by", "engine car"],
    },
    {
        "catid": "VEHHorn",
        "category": "VEHICLES",
        "subcategory": "HORN",
        "synonyms": ["car horn", "honk", "vehicle horn", "beep horn"],
    },
    {
        "catid": "AMBUrbn",
        "category": "AMBIENCE",
        "subcategory": "URBAN",
        "synonyms": [
            "city ambience",
            "street ambience",
            "urban background",
            "traffic ambience",
        ],
    },
    {
        "catid": "AMBForst",
        "category": "AMBIENCE",
        "subcategory": "FOREST",
        "synonyms": [
            "nature ambience",
            "forest ambience",
            "outdoor ambience",
            "birdsong bed",
        ],
    },
    {
        "catid": "AMBRoom",
        "category": "AMBIENCE",
        "subcategory": "ROOM TONE",
        "synonyms": ["room tone", "roomtone", "interior ambience", "quiet room"],
    },
    {
        "catid": "UIBeep",
        "category": "USER INTERFACE",
        "subcategory": "BEEP",
        "synonyms": ["ui beep", "button", "menu click", "notification", "ui blip"],
    },
    {
        "catid": "UIMvmt",
        "category": "USER INTERFACE",
        "subcategory": "MOTION",
        "synonyms": ["ui whoosh", "swipe", "ui swipe", "transition whoosh"],
    },
    {
        "catid": "ANMLDog",
        "category": "ANIMALS",
        "subcategory": "DOG",
        "synonyms": ["dog", "bark", "dog bark", "growl", "whine dog"],
    },
    {
        "catid": "ANMLCat",
        "category": "ANIMALS",
        "subcategory": "CAT DOMESTIC",
        "synonyms": ["cat", "meow", "purr", "cat meow"],
    },
    {
        "catid": "BIRDSong",
        "category": "BIRDS",
        "subcategory": "SONGBIRD",
        "synonyms": ["bird", "birdsong", "chirp", "tweet", "bird call"],
    },
    {
        "catid": "GUNPis",
        "category": "GUNS",
        "subcategory": "PISTOL",
        "synonyms": ["gunshot", "pistol", "handgun", "gun fire", "shot"],
    },
    {
        "catid": "EXPLReal",
        "category": "EXPLOSIONS",
        "subcategory": "REAL",
        "synonyms": ["explosion", "blast", "boom", "detonation", "explode"],
    },
    {
        "catid": "CLOTHMvmt",
        "category": "CLOTH",
        "subcategory": "MOVEMENT",
        "synonyms": [
            "cloth",
            "cloth movement",
            "fabric",
            "clothing rustle",
            "cloth rustle",
        ],
    },
    {
        "catid": "PAPRHndl",
        "category": "PAPER",
        "subcategory": "HANDLE",
        "synonyms": ["paper", "paper rustle", "page turn", "paper crumple"],
    },
    {
        "catid": "MACHMisc",
        "category": "MACHINES",
        "subcategory": "MISC",
        "synonyms": ["machine", "motor", "mechanism", "machinery", "servo"],
    },
    {
        "catid": "ELECBuzz",
        "category": "ELECTRICITY",
        "subcategory": "BUZZ & HUM",
        "synonyms": ["electric buzz", "spark", "zap", "electricity", "arc"],
    },
    {
        "catid": "COMTelph",
        "category": "COMMUNICATIONS",
        "subcategory": "TELEPHONE",
        "synonyms": ["phone ring", "telephone", "ringtone", "cell phone", "dial tone"],
    },
]


#: AudioSet label NAME (lowercased) -> UCS CatID. ``mid`` is best-effort (verify
#: against ``audioset/ontology.json`` before trusting). Every ``catid`` here MUST
#: exist in the UCS table: :func:`~foley.index.taxonomy.audioset.load_audioset_ucs_map`
#: asserts this at load time.
SEED_AUDIOSET_UCS_MAP: list[dict] = [
    {"name": "door", "catid": "DOORWood", "mid": "/m/02dgv"},
    {"name": "sliding door", "catid": "DOORMetl", "mid": "/m/02y_763"},
    {"name": "doorbell", "catid": "BELLDoor", "mid": "/m/03wwcy"},
    {"name": "rain", "catid": "RAIN", "mid": "/m/06mb1"},
    {"name": "raindrop", "catid": "RAIN", "mid": "/m/07r10fb"},
    {"name": "thunder", "catid": "THUN", "mid": "/m/0ngt1"},
    {"name": "thunderstorm", "catid": "THUN", "mid": "/m/0jb2l"},
    {"name": "wind", "catid": "WIND", "mid": "/m/03m9d0z"},
    {"name": "walk, footsteps", "catid": "FEETHmn", "mid": "/m/07qann"},
    {"name": "fire", "catid": "FIREBurn", "mid": "/m/0jbk"},
    {"name": "crackle", "catid": "FIREBurn", "mid": "/m/07pc8k4"},
    {"name": "water", "catid": "WATRFlow", "mid": "/m/0838f"},
    {"name": "splash, splatter", "catid": "WATRSplsh", "mid": "/m/07qlwh6"},
    {"name": "pour", "catid": "WATRPour", "mid": "/m/07q0yl5"},
    {"name": "glass", "catid": "GLASBrk", "mid": "/m/039jq"},
    {"name": "shatter", "catid": "GLASBrk", "mid": "/m/07rjwbb"},
    {"name": "explosion", "catid": "EXPLReal", "mid": "/m/014zdl"},
    {"name": "gunshot, gunfire", "catid": "GUNPis", "mid": "/m/032s66"},
    {"name": "vehicle", "catid": "VEHCar", "mid": "/m/07yv9"},
    {"name": "car", "catid": "VEHCar", "mid": "/m/0k4j"},
    {"name": "vehicle horn, honk", "catid": "VEHHorn", "mid": "/m/0912c9"},
    {"name": "dog", "catid": "ANMLDog", "mid": "/m/0bt9lr"},
    {"name": "bark", "catid": "ANMLDog", "mid": "/m/05tny_"},
    {"name": "cat", "catid": "ANMLCat", "mid": "/m/01yrx"},
    {"name": "bird", "catid": "BIRDSong", "mid": "/m/015p6"},
    {"name": "telephone", "catid": "COMTelph", "mid": "/m/07cx4"},
]
