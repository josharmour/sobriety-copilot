"""Verified public Meeting Guide JSON feeds.

Each feed was probed once and confirmed to return the standard Meeting Guide
JSON spec (https://github.com/code4recovery/spec) with real meeting data.

To extend coverage, append entries here. Most TSML (12 Step Meeting List
WordPress plugin) sites expose the feed at a predictable URL:
    https://{site}/wp-admin/admin-ajax.php?action=meetings
and some declare it in a <link> tag in the page <head>. Probe pattern:
    curl '<URL>' | head -c 200    # should start with '['

Entries default to fellowship "AA" (service.py); set "fellowship" explicitly
for anything else — the /api/meetings filter matches it case-insensitively.
"""

FEEDS: list[dict[str, str]] = [
    # Major US metro AA intergroups — TSML/Meeting Guide JSON, sorted by meeting count.
    {"name": "NY Intergroup",            "home": "https://www.nyintergroup.org",  "url": "https://www.nyintergroup.org/wp-admin/admin-ajax.php?action=meetings",  "region": "New York City metro"},
    {"name": "Houston Intergroup",       "home": "https://aahouston.org",         "url": "https://aahouston.org/wp-admin/admin-ajax.php?action=meetings",         "region": "Greater Houston"},
    {"name": "Orange County CA",         "home": "https://www.oc-aa.org",         "url": "https://www.oc-aa.org/wp-admin/admin-ajax.php?action=meetings",         "region": "Orange County, CA"},
    {"name": "Phoenix Valley",           "home": "https://aaphoenix.org",         "url": "https://aaphoenix.org/wp-admin/admin-ajax.php?action=meetings",         "region": "Phoenix metro"},
    {"name": "Greater Seattle",          "home": "https://www.seattleaa.org",     "url": "https://www.seattleaa.org/wp-admin/admin-ajax.php?action=meetings",     "region": "Puget Sound"},
    {"name": "Atlanta",                  "home": "https://www.atlantaaa.org",     "url": "https://www.atlantaaa.org/wp-admin/admin-ajax.php?action=meetings",     "region": "Atlanta metro"},
    {"name": "Kansas City",              "home": "https://www.kc-aa.org",         "url": "https://www.kc-aa.org/wp-admin/admin-ajax.php?action=meetings",         "region": "Kansas City metro"},
    {"name": "San Diego",                "home": "https://www.aasandiego.org",    "url": "https://www.aasandiego.org/wp-admin/admin-ajax.php?action=meetings",    "region": "San Diego County"},
    {"name": "Denver Area",              "home": "https://daccaa.org",            "url": "https://daccaa.org/wp-admin/admin-ajax.php?action=meetings",            "region": "Denver metro"},
    {"name": "New Mexico (state)",       "home": "https://nm-aa.org",             "url": "https://nm-aa.org/wp-admin/admin-ajax.php?action=meetings",             "region": "New Mexico"},
    {"name": "Washington DC",            "home": "https://aa-dc.org",             "url": "https://aa-dc.org/wp-admin/admin-ajax.php?action=meetings",             "region": "DC / Northern Virginia"},
    {"name": "Nashville",                "home": "https://www.aanashville.org",   "url": "https://www.aanashville.org/wp-admin/admin-ajax.php?action=meetings",   "region": "Middle Tennessee"},
    {"name": "St Louis",                 "home": "https://aastl.org",             "url": "https://aastl.org/wp-admin/admin-ajax.php?action=meetings",             "region": "Greater St Louis"},
    {"name": "Twin Cities",              "home": "https://aaminneapolis.org",     "url": "https://aaminneapolis.org/wp-admin/admin-ajax.php?action=meetings",     "region": "Minneapolis-St Paul"},
    {"name": "East Bay (Oakland/Berk.)", "home": "https://eastbayaa.org",         "url": "https://eastbayaa.org/wp-admin/admin-ajax.php?action=meetings",         "region": "East Bay, CA"},
    {"name": "SF/Marin Intergroup",      "home": "https://aasfmarin.org",         "url": "https://sheets.code4recovery.org/storage/aasfmarin.json",               "region": "SF / Marin"},
    {"name": "Central Ohio",             "home": "https://www.aacentralohio.org", "url": "https://www.aacentralohio.org/wp-admin/admin-ajax.php?action=meetings", "region": "Columbus, OH"},
    {"name": "Silicon Valley",           "home": "https://www.aasanjose.org",     "url": "https://sheets.code4recovery.org/storage/12Ga8uwMG4WJ8pZ_SEU7vNETp_aQZ-2yNVsYDFqIwHyE.json", "region": "San Jose / South Bay"},
    {"name": "Cincinnati",               "home": "https://www.aacincinnati.org",  "url": "https://www.aacincinnati.org/wp-admin/admin-ajax.php?action=meetings",  "region": "Cincinnati metro"},
    {"name": "Tucson",                   "home": "https://www.aatucson.org",      "url": "https://www.aatucson.org/wp-admin/admin-ajax.php?action=meetings",      "region": "Southern Arizona"},
    {"name": "Indianapolis",             "home": "https://www.indyaa.org",        "url": "https://www.indyaa.org/wp-admin/admin-ajax.php?action=meetings",        "region": "Central Indiana"},

    # Adjacent fellowships with live TSML feeds (worldwide lists).
    {"name": "Recovery Dharma",          "home": "https://recoverydharma.org",    "url": "https://recoverydharma.org/wp-admin/admin-ajax.php?action=meetings",    "region": "Worldwide", "fellowship": "Recovery Dharma"},
    {"name": "CMA",                      "home": "https://crystalmeth.org",       "url": "https://crystalmeth.org/wp-admin/admin-ajax.php?action=meetings",       "region": "Worldwide", "fellowship": "CMA"},
]
