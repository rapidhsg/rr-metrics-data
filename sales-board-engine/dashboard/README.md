# Sales Board dashboard

The page the team uses: Board (kanban of the engine's picks), Map (routes), Reps (hours, time off, capacity), Results.

- `index.html` is the page. `zips.json` is Long Island zip shapes for the map.
- `board.json` is NOT kept here: it holds customer names. `python board.py <out> <job export csv>` builds it after `run.py`.
- It is published as a Claude artifact with the files `board.json` and `zips.json` next to it, and the `db` and `user` capabilities.
- Shared state lives in the artifact's database: `cards/<job id>` (manager moves and "Set in AccuLynx"), `roster/<rep slug>` (the Reps tab).
  The roster docs mirror the `roster` section of `assignment_rules.json`.
- Republishing to a new account: publish `index.html` with those two files, then load the roster docs from `assignment_rules.json`.
