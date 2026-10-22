# Separate marketing workflow demo

Public route: `/showcase/marketing-workflow/`.

The standalone build opens on the main Meta-style creative outcome. Google Ads,
Mailchimp, Klaviyo, AURA coordination, measurement and approvals are six closed
dropdowns. Supporting tool screens mount only when their dropdown opens.

Choose **Watch how AURA worked** for a 12-scene guided tour: main outcome, request,
plan, input review, local playback, the creative, supporting tools, coordination,
and approvals. Play, pause, previous, next and scene selection are available.
`?screen=input` starts at the prepared request; `?tour=1` plays the tour;
`?scene=N` opens one paused scene. The final scene returns to the main outcome.

All four tools, account identifiers and data are synthetic in this public demo.
The signed-in account review and its private discovery responses are not used.
The prepared fixture retains the same products, offers, draft copy and separate
Meta Ads / Klaviyo attribution. Each task retains its required implementation
approval. AURA is shown as the coordinator, not a substitute execution tool.

`vite.marketing.config.js` produces an isolated bundle. Its module-graph guard
rejects live account clients; the entry page denies connections and forms with
Content Security Policy. Playback and downloads stay local. No sign-in, provider
API call, campaign launch, budget change, native draft save or send occurs.

Validation includes main-outcome-first order, closed default dropdowns, explicit
tool expansion, all walkthrough scenes, original simulation totals, separate
attribution and exclusion of private account identifiers.
