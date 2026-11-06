# TFG Cricket Rivalry — MongoDB / Railway

Telegram group hand-cricket bot built with Python, Aiogram 3 and MongoDB (PyMongo async client). AI team members can be added to rosters, but AI-controlled batting/bowling is intentionally not included.

## Included workflows

- `/start`, `/help`, `/newmatch`, Team Match lobby, first-tap host claim, `/join_a`, `/join_b`, and 5-minute join window with `/extend`.
- Host roster management: `/add_a`, `/add_b`, `/swap`, `/remove_player`, `/add_ai_a`, `/add_ai_b`, `/remove_ai`.
- Host match setup: 1–50 overs, 1–25 wickets or Auto (All Out), No-Ball ON/OFF, Normal/Rainy weather, Power Play ON/OFF.
- Captain selection, toss, winning-captain Bat/Bowl decision, opening striker/non-striker/bowler selection with confirmation.
- Bowler private-DM number submission (1–6), batter group number submission (1–6), 60-second persisted timeout, restart recovery, and timeout bowler replacement prompt.
- Requested custom No-Ball behavior: when enabled, unequal bowler/batter numbers award the batter's number plus one no-ball extra; equal numbers are a wicket. No-ball deliveries do not consume a legal ball.
- Power Play defaults: first two overs, a 6 attempt has 30% SIX / 70% OUT; final two overs, a 4/6 attempt has 50% chance to retain the boundary. Constants are editable in `bot/handlers/game.py`.
- Four/six/run/wicket/no-ball media slots, individual run milestones, partnership milestones, hat-trick tracking, wicket roster, Bring Back controls.
- Over summaries, `/status`, innings break, host `/swap_innings`, second innings target, final winner/margin and statistical awards.
- `/change_host`, `/endgame` (Host or Telegram group admin), MongoDB persistence and Railway polling deployment files.

## Important rule notes / remaining limitations

This is an improved runnable project bundle, but it is **not yet production-certified** and has not been live-tested against your Telegram bot, Telegram group, MongoDB Atlas or Railway deployment.

- Rainy weather currently applies a simple configurable 20% overs reduction for matches set to 10–50 overs. It is **not an official DLS calculation**.
- The number-input gameplay does not yet provide separate delivery-entry controls for wides, byes, leg-byes or penalty runs. The scorecard has extra categories reserved, but those categories cannot be independently recorded yet.
- Maiden overs and dot-ball awards are not meaningful/recordable in the current 1–6-only input flow.
- Power Play probabilities are editable defaults, not calibrated tournament rules.
- Awards are derived from available batting/bowling totals; Player of the Match is a transparent heuristic, not an official scoring model.
- Telegram media file IDs and group deep links must be tested with your bot. All media insertion slots are in `bot/services/event_media.py` and currently default to `None`.
- The `1v1`, `Play vs Assistant`, `Solo`, `Arena`, and Updates menu destinations are not implemented as playable modes. Team Match is the implemented mode.

## Local setup

1. Create a Telegram bot with BotFather and copy its token.
2. Create a MongoDB Atlas cluster/database user. Allow Railway network access.
3. Copy `.env.example` to `.env` and set `BOT_TOKEN`, `MONGODB_URI`, `MONGODB_DATABASE`.
4. Install Python 3.11+ and dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m bot.main
   ```

## Railway deployment

1. Push the contents of this folder to GitHub.
2. Create a Railway project from that repository.
3. Add variables: `BOT_TOKEN`, `MONGODB_URI`, `MONGODB_DATABASE`.
4. Railway uses `railway.toml` / `Procfile` to run `python -m bot.main`.
5. Add the bot to a private Telegram test group and allow it to send messages/videos/GIFs.
6. Disable BotFather privacy mode so the bot can read plain-number messages in the group.

## Add your media

Edit `bot/services/event_media.py`. Replace `None` with a Telegram `file_id` or a local path under `media/`. Every insertion point has a clear comment: welcome banner, match start, innings break, innings 2, each run, four, six, wicket, no-ball, milestones, partnership, hat-trick and match result.

## Test status

- Python bytecode compilation: passed.
- Included unit tests: 3/3 passed.
- ZIP integrity: checked after packaging.
- Full dependency import, MongoDB integration, Telegram callbacks and Railway deployment: not tested in this environment (Aiogram is not installed in the packaging runtime and external credentials are not available).
