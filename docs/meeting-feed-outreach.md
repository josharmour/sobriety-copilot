# Meeting feed outreach

The meeting catalog (`src/meetings/feeds.py`) reads each intergroup's public
Meeting Guide feed. The sites below run the same 12 Step Meeting List plugin
but answer **401**, which means the office has switched public feed sharing
off. That was their choice, so we don't scrape or work around it. We ask. The
plugin lets an admin issue a feed key to a named app. Once a key arrives, add
the feed with the key in its URL (`...?action=meetings&key=KEY`).

Found 2026-09-22 by `scripts/discover_meeting_feeds.py` (re-run it to refresh
this list).

| Office | Site | Area |
|---|---|---|
| Central Ohio Intergroup | aacentralohio.org | Columbus, OH (removed from feeds.py; was 401) |
| Boston Central Service | aaboston.org | Greater Boston |
| Dallas Intergroup | aadallas.org | Dallas |
| Fort Worth | fortworthaa.org | Fort Worth |
| Austin Intergroup | austinaa.org | Austin |
| Portland Intergroup | pdxaa.org | Portland, OR |
| Miami-Dade | aamiamidade.org | Miami |
| Central Florida Intergroup | cflintergroup.org | Orlando |
| Daytona | aadaytona.org | Volusia County, FL |
| Pensacola | aapensacola.org | NW Florida |
| Charlotte | charlotteaa.org | Charlotte, NC |
| North Carolina | aanorthcarolina.org | North Carolina |
| Asheville | ashevilleaa.org | Western NC |
| Cleveland District Office | aacle.org | Cleveland |
| SE Michigan | aa-semi.org | Detroit metro |
| Minnesota | aaminnesota.org | Minnesota |
| Salt Lake Central Office | saltlakeaa.org | Salt Lake City |
| Colorado Springs | coloradospringsaa.org | Colorado Springs |
| Albuquerque | albuquerqueaa.org | Albuquerque |
| Western Washington (Area 72) | area72aa.org | Western WA |
| Salem | aasalem.org | Salem, OR |
| Santa Cruz | aasantacruz.org | Santa Cruz, CA |
| Peoria | aapeoria.org | Central Illinois |
| Arkansas | arkansasaa.org | Arkansas |
| North Dakota | aanorthdakota.org | North Dakota |
| Anchorage | anchorageaa.org | Anchorage |
| Vancouver | vancouveraa.ca / vancouveraa.org | Greater Vancouver |

Sites that returned HTML or connection errors weren't counted. They may use
a different meeting-list system and need individual research.

## Request template

Send this through the office's contact form or email. Keep it short, and have
one named person send it; offices respond to people, not to apps.

> Subject: Request for a Meeting Guide feed key for Sobriety Copilot
>
> Hello,
>
> I run Sobriety Copilot (https://sobrietycopilot.com), a recovery
> companion app. Its "Find a meeting" screen lists local meetings straight
> from intergroup meeting lists, and links every listing back to your site as
> the source.
>
> Your site uses the 12 Step Meeting List plugin with feed sharing
> restricted. Would you be willing to issue us a feed key? We:
>
> - read the feed at most once an hour and cache it,
> - never modify or republish your data outside the app, and show your office as
>   the source with a link back,
> - don't store who searches for meetings or where,
> - will stop listing your meetings whenever you ask.
>
> If you'd rather we didn't list your meetings, that's fine too. Just let us
> know. Thank you for the service you do.
>
> [name], Sobriety Copilot · [contact email]
