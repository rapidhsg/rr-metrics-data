# Sales Board dashboard

The page the team uses: Board (kanban of the engine's picks), CSR Guide, Map (routes), Reps (hours, time off, capacity), Results.

CSR booking guide (fold on the Board tab follows the selected day; the CSR Guide tab always starts at today): open spots each rep can still take, then the
next 3 days, best spots first (close rate x average ticket). Built in the page from the board as it stands, so manager moves and days off
change it instantly. Same-day spots need 1 hour of lead time and the sales manager's OK. Late in the day with nothing left, it leads with
tomorrow. Includes calls to make (move up, reschedule, nobody free). "Copy for CSRs" puts a plain-text version on the clipboard.

- `index.html` is the page. `zips.json` is Long Island zip shapes for the map.
- `board.json` is NOT kept here: it holds customer names. `python board.py <out> <job export csv>` builds it after `run.py`.
- It is published as a Claude artifact with the files `board.json` and `zips.json` next to it, and the `db` and `user` capabilities.
- Shared state lives in the artifact's database: `cards/<job id>` (manager moves and "Set in AccuLynx"), `roster/<rep slug>` (the Reps tab).
  The roster docs mirror the `roster` section of `assignment_rules.json`.
- Republishing to a new account: publish `index.html` with those two files, then load the roster docs from `assignment_rules.json`.
