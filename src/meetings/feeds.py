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

Finding more: `python scripts/discover_meeting_feeds.py --generate-us` probes
likely intergroup domains. Sites answering 401 have turned public sharing off
on purpose (Central Ohio, Boston, Dallas, ...) — don't work around that; the
outreach list and a request template are in docs/meeting-feed-outreach.md.
Watch /api/meetings/sources after deploying: a feed stuck at "error"/"empty"
means its URL moved or it started blocking us.
"""

# Honest, identifiable UA for every upstream. Several Cloudflare-fronted
# intergroup sites 403 a spoofed desktop-Chrome UA from a server (it fails
# their browser fingerprint check) but serve this one — spoofing cost ~6,300
# meetings (Atlanta, Kansas City, DC, New Mexico, East Bay, Tucson).
USER_AGENT = "sobriety-copilot/1.0 (+https://sobrietycopilot.com)"

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
    {"name": "Silicon Valley",           "home": "https://www.aasanjose.org",     "url": "https://sheets.code4recovery.org/storage/12Ga8uwMG4WJ8pZ_SEU7vNETp_aQZ-2yNVsYDFqIwHyE.json", "region": "San Jose / South Bay"},
    {"name": "Cincinnati",               "home": "https://www.aacincinnati.org",  "url": "https://www.aacincinnati.org/wp-admin/admin-ajax.php?action=meetings",  "region": "Cincinnati metro"},
    {"name": "Tucson",                   "home": "https://www.aatucson.org",      "url": "https://www.aatucson.org/wp-admin/admin-ajax.php?action=meetings",      "region": "Southern Arizona"},
    {"name": "Indianapolis",             "home": "https://www.indyaa.org",        "url": "https://www.indyaa.org/wp-admin/admin-ajax.php?action=meetings",        "region": "Central Indiana"},

    # Added 2026-09-22 via scripts/discover_meeting_feeds.py (local intergroups).
    {"name": "Connecticut", "home": "https://www.ct-aa.org", "url": "https://www.ct-aa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Connecticut"},
    {"name": "SE Pennsylvania (SEPIA)", "home": "https://www.aasepia.org", "url": "https://www.aasepia.org/wp-admin/admin-ajax.php?action=meetings", "region": "Philadelphia metro"},
    {"name": "Oakland County MI", "home": "https://www.aaoakland.org", "url": "https://www.aaoakland.org/wp-admin/admin-ajax.php?action=meetings", "region": "Oakland County, MI (Detroit north)"},
    {"name": "Capital District NY", "home": "https://www.albanyaa.org", "url": "https://www.albanyaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Albany / Capital District, NY"},
    {"name": "Central California", "home": "https://www.aasacramento.org", "url": "https://www.aasacramento.org/wp-admin/admin-ajax.php?action=meetings", "region": "Sacramento metro"},
    {"name": "Las Vegas", "home": "https://www.lvcentraloffice.org", "url": "https://www.lvcentraloffice.org/wp-admin/admin-ajax.php?action=meetings", "region": "Las Vegas metro"},
    {"name": "San Antonio", "home": "https://www.aasanantonio.org", "url": "https://www.aasanantonio.org/wp-admin/admin-ajax.php?action=meetings", "region": "San Antonio metro"},
    {"name": "Inland Empire", "home": "https://www.aainlandempire.org", "url": "https://www.aainlandempire.org/wp-admin/admin-ajax.php?action=meetings", "region": "Riverside / San Bernardino, CA"},
    {"name": "Suffolk County NY", "home": "https://www.suffolkny-aa.org", "url": "https://www.suffolkny-aa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Suffolk County, Long Island"},
    {"name": "Greater Fresno", "home": "https://www.fresnoaa.org", "url": "https://www.fresnoaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Fresno / Central Valley, CA"},
    {"name": "Rhode Island", "home": "https://www.rhodeisland-aa.org", "url": "https://www.rhodeisland-aa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Rhode Island / SE Massachusetts"},
    {"name": "Grand Rapids", "home": "https://www.grandrapidsaa.org", "url": "https://www.grandrapidsaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "West Michigan"},
    {"name": "Omaha", "home": "https://www.omahaaa.org", "url": "https://www.omahaaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Omaha metro"},
    {"name": "Nassau County NY", "home": "https://nassauintergroup.org", "url": "https://nassauintergroup.org/wp-admin/admin-ajax.php?action=meetings", "region": "Nassau County, Long Island"},
    {"name": "Palm Beach County", "home": "https://aapalmbeachcounty.org", "url": "https://aapalmbeachcounty.org/wp-admin/admin-ajax.php?action=meetings", "region": "Palm Beach County, FL"},
    {"name": "Greater Toronto", "home": "https://www.aatoronto.org", "url": "https://www.aatoronto.org/wp-admin/admin-ajax.php?action=meetings", "region": "Greater Toronto Area"},
    {"name": "Calgary", "home": "https://www.calgaryaa.org", "url": "https://www.calgaryaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Calgary, AB"},
    {"name": "Richmond VA", "home": "https://www.aarichmond.org", "url": "https://www.aarichmond.org/wp-admin/admin-ajax.php?action=meetings", "region": "Richmond, VA"},
    {"name": "Syracuse", "home": "https://www.aasyracuse.org", "url": "https://www.aasyracuse.org/wp-admin/admin-ajax.php?action=meetings", "region": "Central New York"},
    {"name": "Greater Columbia SC", "home": "https://www.aacolumbia.org", "url": "https://www.aacolumbia.org/wp-admin/admin-ajax.php?action=meetings", "region": "Columbia, SC"},
    {"name": "Memphis", "home": "https://www.memphis-aa.org", "url": "https://www.memphis-aa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Memphis metro"},
    {"name": "Naples FL", "home": "https://www.aanaples.org", "url": "https://www.aanaples.org/wp-admin/admin-ajax.php?action=meetings", "region": "Naples / Collier County, FL"},
    {"name": "Edmonton", "home": "https://www.edmontonaa.org", "url": "https://www.edmontonaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Edmonton, AB"},
    {"name": "Myrtle Beach", "home": "https://aamyrtlebeach.org", "url": "https://aamyrtlebeach.org/wp-admin/admin-ajax.php?action=meetings", "region": "Grand Strand, SC"},
    {"name": "Ottawa", "home": "https://www.ottawaaa.org", "url": "https://www.ottawaaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Ottawa / Eastern Ontario"},
    {"name": "Des Moines", "home": "https://www.aadesmoines.org", "url": "https://www.aadesmoines.org/wp-admin/admin-ajax.php?action=meetings", "region": "Des Moines, IA"},
    {"name": "Spokane", "home": "https://www.aaspokane.org", "url": "https://www.aaspokane.org/wp-admin/admin-ajax.php?action=meetings", "region": "Spokane / Inland Northwest"},
    {"name": "Fort Wayne", "home": "https://www.aafortwayne.org", "url": "https://www.aafortwayne.org/wp-admin/admin-ajax.php?action=meetings", "region": "NE Indiana"},
    {"name": "Harrisburg", "home": "https://www.aaharrisburg.org", "url": "https://www.aaharrisburg.org/wp-admin/admin-ajax.php?action=meetings", "region": "Harrisburg, PA"},
    {"name": "Lancaster PA", "home": "https://www.lancasteraa.org", "url": "https://www.lancasteraa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Lancaster County, PA"},
    {"name": "Springfield IL", "home": "https://www.aaspringfield.org", "url": "https://www.aaspringfield.org/wp-admin/admin-ajax.php?action=meetings", "region": "Springfield, IL"},
    {"name": "Santa Fe", "home": "https://santafeaa.org", "url": "https://santafeaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Santa Fe, NM"},
    {"name": "Mobile AL", "home": "https://www.mobileaa.org", "url": "https://www.mobileaa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Mobile, AL"},
    {"name": "Roanoke Valley", "home": "https://www.aaroanoke.org", "url": "https://www.aaroanoke.org/wp-admin/admin-ajax.php?action=meetings", "region": "Roanoke, VA"},
    {"name": "Halifax", "home": "https://www.aahalifax.org", "url": "https://www.aahalifax.org/wp-admin/admin-ajax.php?action=meetings", "region": "Halifax, NS"},
    {"name": "Lakeshore (Durham ON)", "home": "https://www.aadurham.org", "url": "https://www.aadurham.org/wp-admin/admin-ajax.php?action=meetings", "region": "Durham Region, ON"},

    # Statewide / area lists. Listed after the local intergroups so search's
    # dedupe keeps the local listing when both carry the same meeting.
    {"name": "Virginia (Area 71)", "home": "https://aavirginia.org", "url": "https://aavirginia.org/wp-admin/admin-ajax.php?action=meetings", "region": "Virginia"},
    {"name": "Iowa", "home": "https://www.aa-iowa.org", "url": "https://www.aa-iowa.org/wp-admin/admin-ajax.php?action=meetings", "region": "Iowa"},
    {"name": "Mississippi", "home": "https://www.aa-mississippi.org", "url": "https://www.aa-mississippi.org/wp-admin/admin-ajax.php?action=meetings", "region": "Mississippi"},
    {"name": "Vermont", "home": "https://www.aavt.org", "url": "https://www.aavt.org/wp-admin/admin-ajax.php?action=meetings", "region": "Vermont"},
    {"name": "Oregon (Area 58)", "home": "https://www.aa-oregon.org", "url": "https://www.aa-oregon.org/wp-admin/admin-ajax.php?action=meetings", "region": "Oregon"},

    # Adjacent fellowships with live TSML feeds (worldwide lists).
    {"name": "Recovery Dharma",          "home": "https://recoverydharma.org",    "url": "https://recoverydharma.org/wp-admin/admin-ajax.php?action=meetings",    "region": "Worldwide", "fellowship": "Recovery Dharma"},
    {"name": "CMA",                      "home": "https://crystalmeth.org",       "url": "https://crystalmeth.org/wp-admin/admin-ajax.php?action=meetings",       "region": "Worldwide", "fellowship": "CMA"},
]
