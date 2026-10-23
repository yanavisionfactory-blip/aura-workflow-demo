# AURA SEO workflow walkthrough

The separate `showcase/first-choice-seo/` entry uses AURA's existing workspace,
command, plan, action review and execution components. It runs without sign-in.
The existing production AURA interface and authenticated results are unchanged.

The main result opens a full article in a simulated WordPress post editor.
Dallas, Plano and Richardson have distinct newly authored articles. Other tool
outputs start in closed dropdowns and each has a View in tool screen: Google Ads
Keyword Planner, Geo+ mapping, RankMath and Asana.

The review action supports simulated AI instructions, manual editing, before/
after comparison, undo, cancel and explicit local saving. Saved revisions update
all previews and the downloaded package. No tool writes or publishing occur.

## Public content boundary

This public walkthrough is entirely synthetic. `scripts/create-synthetic-seo-fixture.py`
creates all three articles, nine SEO fields and twelve invented keyword rows
without reading emails, attachments, reports, exports or account data. It does
not reproduce the private source fixture prepared in a different local branch.
All metrics are visibly labelled as simulated, all approvals remain pending,
and all URLs use a reserved example domain.

Keyword research, client claims, contact information, images, tool connections
and reviewer assignments require validation before a real client run. Imagify,
exact-site audits, backlinks, rankings, traffic and inquiries are not executed
or measured. No real SEO scores or performance outcomes are claimed.

The ZIP includes an immutable synthetic baseline, current demo revisions,
escaped HTML articles, sample keyword CSV and proposed Asana review tasks.
The build excludes live account modules and sets `connect-src 'none'`.

## Review routes

- `?tour=1`: full AURA walkthrough with Pause, Back and Next.
- `?screen=results`: main WordPress output first, other tools in dropdowns.
- `?screen=review`: draft-preparation action with editing controls.
- `?screen=video`: generated captioned walkthrough.
- `?screen=sources`: synthetic-data disclosure and live-pilot requirements.

The checks cover synthetic-fixture provenance, immutable baseline versus edited
drafts, pending approvals, HTML escaping, all screens and every guided scene.
The build-time browser restricts requests to its local static server, captures
thirteen scenes, tests editing and persistence, and checks mobile width. A
pinned encoder produces the captioned walkthrough MP4 and VTT. Existing website-
content tests also run to protect the earlier demo.
