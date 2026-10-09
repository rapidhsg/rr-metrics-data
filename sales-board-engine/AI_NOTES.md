# AI note reading (for Claude)

## After each AccuLynx pull: tag new notes

1. Load the job export through `engine.load()`. Take jobs with INITIAL LEAD NOTES whose guid is not yet in
   `memory/note_tags.json`.
2. Read each note and give it tags from the list below. Only tag what the note actually says.
3. If a note shows something important that no tag covers, add a new short tag (lowercase, words joined by `_`) and add
   it to the list in `memory/note_tags.json` under `vocabulary` with a one-line meaning.
4. Save `{"vocabulary": {...}, "tags": {"<guid>": ["tag", ...]}}`. Never store phone numbers, emails or addresses.

Starting tags:
- `urgent`: wants it done soon, active damage, deadline
- `active_leak`: water coming in now
- `no_problem_just_old`: no leak or damage, roof is just old
- `roof_age_20_plus`, `roof_age_15_20`, `roof_age_under_15`
- `full_replacement`, `repair_only`, `not_sure_repair_or_replace`
- `both_owners_home`, `one_owner_only`
- `other_quotes`: has met or will meet other contractors
- `first_call`: we are the first company
- `financing_interest`, `price_worry`
- `insurance_claim`
- `referral_or_past_customer`
- `selling_or_buying_home`
- `specialty_material`: slate, cedar, metal, tile, synthetic, designer
- `commercial_or_flat`
- `skylight_chimney_gutters`: other work mentioned

## Weekly: review the misses

1. Run `selftest.py`.
2. From the last 60 days of finished sits, take the 20 the engine rated highest that did not close and the 20 it rated
   lowest that did.
3. Read those notes and look for patterns the tags miss. Add new tags for them and tag those sits.
4. A new tag becomes an input once it is on 15+ sits. The next self-test shows whether it helped. Write what was looked
   at and what was added to `memory/learning_log.md` in plain words.
