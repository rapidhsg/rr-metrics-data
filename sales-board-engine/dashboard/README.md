# Sales Board dashboard

The page the team uses: Board (kanban of the engine's picks), CSR Guide, Map (routes), Reps (hours, time off, capacity), Results.

CSR booking guide (fold on the Board tab: the selected day only, short, with Copy for CSRs; the CSR Guide tab: today plus 3 days in detail): open spots each rep can still take, then the
next 3 days, best spots first (close rate x average ticket). Built in the page from the board as it stands, so manager moves and days off
change it instantly. Same-day spots need 1 hour of lead time and the sales manager's OK. Late in the day with nothing left, it leads with
tomorrow. Rep names are suggestions only: CSRs run every booking by the sales manager, who assigns the rep. Moves (move up, reschedule, nobody free) are worded as proposals for the sales manager. "Copy for CSRs" puts a plain-text version on the clipboard.

- `index.html` is the page. `zips.json` is Long Island zip shapes for the map.
- `board.json` is NOT kept here: it holds customer names. `python board.py <out> <job export csv>` builds it after `run.py`.
- It is published as a Claude artifact with the files `board.json` and `zips.json` next to it, and the `db` and `user` capabilities.
- Shared state lives in the artifact's database: `cards/<job id>` (manager moves and "Set in AccuLynx"), `roster/<rep slug>` (the Reps tab).
  The roster docs mirror the `roster` section of `assignment_rules.json`.
- Republishing to a new account: publish `index.html` with those two files, then load the roster docs from `assignment_rules.json`.

Copy plan (Board tab, next to Reset, and on the red "needs a rep" bar): copies the selected day's whole plan as text. Appointments with no
rep come first, each with a fix that tries the top closer for it first: hand one of his appointments to another rep at the same time, or
move the homeowner to a time he's free. Then every rep's appointments, who's off, and the call center guide for that day.

Availability tab: one week at a time (this week by default, next week from Friday on). Each rep and day has a Working/Off switch and a
6 PM switch (can he run evening appointments that day). Changes save to the rep's roster doc as days_off, days_on (works a day his weekly
schedule doesn't cover, standard 10 to 7 hours), eve_off (no 6 PMs, last start 5 PM) and eve_on (6 PMs allowed, last start 7 PM, no
home-by). The board re-plans right away and the engine reads them on its next run (assign.slot_for).
Suggestions: weekends rotate among reps whose weekly schedule includes weekends, enough reps for the usual weekend volume (about 2.5
appointments each), whoever worked the fewest weekend days in the last 4 weeks first, then the stronger closer. 6 PMs rotate the same way,
sized to twice the usual evening share of appointments. Anyone with an appointment already booked that day (or that evening) keeps it.
Each row shows days working out of the 2-week window (target 11 of 14), weekend days and 6 PMs run in the last 4 weeks.

Held days: the first time the manager moves a card on a day, every other card on that day is held where it is (cards/<id> with pin: true).
After that nothing on that day is rearranged automatically: not by days off, 6 PM switches, or engine refreshes (assign.board_holds gives
held and moved cards a strong preference, so the engine plans new appointments around them). "Suggest changes" (Board tab, on a held day)
lists what should move, keeping the manager's own moves: only cards that no longer fit, or a full re-plan of the held cards when a working
rep has nothing that day. Each suggestion can be applied on its own or all at once. Reset this day releases the hold.
