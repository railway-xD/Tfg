import random
import asyncio
import uuid
from html import escape
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters.command import CommandObject
from bson import ObjectId

from bot.db import matches
from bot.services.event_media import send_event_media
from bot.services.formatting import mention
from bot.services.statistics import (
    overs_text,
    strike_rate,
    economy,
    run_rate,
    extras_total
)

router = Router()

# Power-play probabilities
POWERPLAY_EARLY_SIX_CHANCE = 0.30
POWERPLAY_LATE_BOUNDARY_CHANCE = 0.50


def _member(match, side, user_id):
    if user_id is None:
        return None

    return next(
        (
            p for p in match["teams"][side]["members"]
            if int(p["user_id"]) == int(user_id)
        ),
        None
    )


def _member_any(match, user_id):
    if user_id is None:
        return None, None

    for side in ("A", "B"):
        player = _member(match, side, user_id)

        if player:
            return player, side

    return None, None


async def _active(chat_id):
    return await matches.find_one(
        {"chat_id": chat_id, "status": "live"},
        sort=[("created_at", -1)]
    )


async def _can_choose(callback, match, side):
    return callback.from_user.id in (
        match.get("host_id"),
        match["teams"][side].get("captain_id")
    )


async def begin_opening_selection(message, match, batting, bowling):
    match_id = str(match["_id"])

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "opening_selection_pending": True,
                "pending_selections": {}
            },
            "$unset": {
                "pending_selection": ""
            }
        }
    )

    batting_players = match["teams"][batting]["members"]
    bowling_players = match["teams"][bowling]["members"]

    await message.answer(
        f"🏏 <b>TEAM {batting} CAPTAIN: CHOOSE OPENING STRIKER</b>",
        reply_markup=_player_keyboard(
            "striker",
            match_id,
            batting_players
        )
    )

    await message.answer(
        f"⚾ <b>TEAM {bowling} CAPTAIN: CHOOSE OPENING BOWLER</b>",
        reply_markup=_player_keyboard(
            "bowler",
            match_id,
            bowling_players
        )
    )


def _player_keyboard(role, match_id, players, exclude=None):
    exclude = {int(uid) for uid in (exclude or [])}
    rows = []

    for player in players:
        user_id = int(player["user_id"])

        if user_id in exclude or player.get("is_ai"):
            continue

        rows.append([
            InlineKeyboardButton(
                text=player["name"][:45],
                callback_data=(
                    f"pick:{role}:{match_id}:{user_id}"
                )
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard(role, match_id, user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Confirm",
                callback_data=(
                    f"pickconfirm:{role}:{match_id}:{user_id}"
                )
            ),
            InlineKeyboardButton(
                text="❌ Cancel",
                callback_data=(
                    f"pickcancel:{role}:{match_id}"
                )
            )
        ]]
    )


@router.callback_query(F.data.startswith("pick:"))
async def pick_player(callback: CallbackQuery):
    _, role, match_id, user_id = callback.data.split(":")
    user_id = int(user_id)

    if role not in ("striker", "non_striker", "bowler"):
        await callback.answer(
            "Invalid selection!",
            show_alert=True
        )
        return

    match = await matches.find_one({
        "_id": ObjectId(match_id),
        "chat_id": callback.message.chat.id,
        "status": "live"
    })

    if not match:
        await callback.answer(
            "Match not found",
            show_alert=True
        )
        return

    inn = match["innings"][match["current_innings"] - 1]

    side = (
        inn["bowling"]
        if role == "bowler"
        else inn["batting"]
    )

    if not await _can_choose(callback, match, side):
        await callback.answer(
            "Only Host or the relevant Captain Can Choose!",
            show_alert=True
        )
        return

    player = _member(match, side, user_id)

    if not player or player.get("is_ai"):
        await callback.answer(
            "Player is not available in this team!",
            show_alert=True
        )
        return

    current = match.get("current", {})

    if role == "non_striker":
        if user_id == current.get("striker_id"):
            eligible = [
                p for p in match["teams"][side]["members"]
                if not p.get("is_ai")
            ]

            if len(eligible) > 1:
                await callback.answer(
                    "Striker cannot be the non-striker!",
                    show_alert=True
                )
                return

    pending = {
        "role": role,
        "user_id": user_id,
        "name": player["name"],
        "side": side
    }

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                f"pending_selections.{role}": pending
            }
        }
    )

    await callback.message.answer(
        f"Confirm {role.replace('_', ' ')}: "
        f"{mention(user_id, player['name'])}?",
        reply_markup=_confirm_keyboard(
            role,
            match_id,
            user_id
        )
    )

    await callback.answer("Selection ready to confirm")


@router.callback_query(F.data.startswith("pickcancel:"))
async def cancel_pick(callback: CallbackQuery):
    _, role, match_id = callback.data.split(":")

    if role not in ("striker", "non_striker", "bowler"):
        await callback.answer(
            "Invalid selection!",
            show_alert=True
        )
        return

    match = await matches.find_one({
        "_id": ObjectId(match_id),
        "chat_id": callback.message.chat.id,
        "status": "live"
    })

    if not match:
        await callback.answer(
            "Match not found",
            show_alert=True
        )
        return

    if callback.from_user.id != match.get("host_id"):
        await callback.answer(
            "Only Host Can Cancel This Selection!",
            show_alert=True
        )
        return

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$unset": {
                f"pending_selections.{role}": ""
            }
        }
    )

    inn = match["innings"][match["current_innings"] - 1]

    side = (
        inn["bowling"]
        if role == "bowler"
        else inn["batting"]
    )

    exclude = []

    if role == "non_striker":
        striker_id = match.get("current", {}).get("striker_id")

        eligible = [
            p for p in match["teams"][side]["members"]
            if not p.get("is_ai")
        ]

        if striker_id is not None and len(eligible) > 1:
            exclude = [int(striker_id)]

    await callback.message.answer(
        f"Choose {role.replace('_', ' ')} again:",
        reply_markup=_player_keyboard(
            role,
            match_id,
            match["teams"][side]["members"],
            exclude
        )
    )

    await callback.answer("Selection cancelled")


async def _maybe_finish_opening_selection(message, match_id):
    match = await matches.find_one({
        "_id": match_id,
        "status": "live",
        "opening_selection_pending": True
    })

    if not match:
        return

    current = match.get("current", {})

    if not all((
        current.get("striker_id"),
        current.get("non_striker_id"),
        current.get("bowler_id")
    )):
        return

    result = await matches.update_one(
        {
            "_id": match_id,
            "status": "live",
            "opening_selection_pending": True,
            "current.striker_id": current["striker_id"],
            "current.non_striker_id": current["non_striker_id"],
            "current.bowler_id": current["bowler_id"]
        },
        {
            "$set": {
                "opening_selection_pending": False
            }
        }
    )

    if result.modified_count != 1:
        return

    latest = await matches.find_one({"_id": match_id})

    if latest:
        await _announce_next_ball(message, latest)


@router.callback_query(F.data.startswith("pickconfirm:"))
async def confirm_pick(callback: CallbackQuery):
    _, role, match_id, user_id = callback.data.split(":")
    user_id = int(user_id)

    if role not in ("striker", "non_striker", "bowler"):
        await callback.answer(
            "Invalid selection!",
            show_alert=True
        )
        return

    match = await matches.find_one({
        "_id": ObjectId(match_id),
        "chat_id": callback.message.chat.id,
        "status": "live"
    })

    if not match:
        await callback.answer(
            "Match not found",
            show_alert=True
        )
        return

    pending = match.get("pending_selections", {}).get(role)

    if not pending:
        old_pending = match.get("pending_selection", {})

        if old_pending.get("role") == role:
            pending = old_pending

    if (
        not pending
        or int(pending.get("user_id", 0)) != user_id
    ):
        await callback.answer(
            "This selection is no longer pending!",
            show_alert=True
        )
        return

    side = pending["side"]

    if callback.from_user.id not in (
        match.get("host_id"),
        match["teams"][side].get("captain_id")
    ):
        await callback.answer(
            "Only Host or relevant Captain Can Confirm!",
            show_alert=True
        )
        return

    inn_index = match["current_innings"] - 1

    update_result = await matches.update_one(
        {
            "_id": match["_id"],
            f"pending_selections.{role}.user_id": user_id
        },
        {
            "$set": {
                f"current.{role}_id": user_id
            },
            "$unset": {
                f"pending_selections.{role}": "",
                "pending_selection": ""
            }
        }
    )

    if update_result.modified_count != 1:
        await callback.answer(
            "Selection changed. Please select again.",
            show_alert=True
        )
        return

    if role in ("striker", "non_striker"):
        await matches.update_one(
            {
                "_id": match["_id"],
                f"innings.{inn_index}.batters.{user_id}": {
                    "$exists": False
                }
            },
            {
                "$set": {
                    f"innings.{inn_index}.batters.{user_id}": {
                        "name": pending["name"],
                        "runs": 0,
                        "balls": 0,
                        "fours": 0,
                        "sixes": 0,
                        "out": False
                    }
                }
            }
        )

    elif role == "bowler":
        await matches.update_one(
            {
                "_id": match["_id"],
                f"innings.{inn_index}.bowlers.{user_id}": {
                    "$exists": False
                }
            },
            {
                "$set": {
                    f"innings.{inn_index}.bowlers.{user_id}": {
                        "name": pending["name"],
                        "runs": 0,
                        "wickets": 0,
                        "legal_balls": 0,
                        "maidens": 0
                    }
                }
            }
        )

    await callback.message.answer(
        f"✅ New {'bowler' if role == 'bowler' else 'batter'}: "
        f"{mention(user_id, pending['name'])}"
    )

    await callback.answer("Selection confirmed")

    latest = await matches.find_one({"_id": match["_id"]})

if not latest:
    return

current = latest.get("current", {})
latest_inn = latest["innings"][latest["current_innings"] - 1]

if (
    current.get("striker_id")
    and current.get("non_striker_id")
    and current.get("bowler_id")
    and not latest.get("needs_new_bowler")
):
    await _announce_next_ball(callback.message, latest)

    # Opening selection handling continues in Part 2.

    # Opening selection: wait until all three players are selected.
    if latest.get("opening_selection_pending"):
        if (
            role == "striker"
            and current.get("non_striker_id") is None
        ):
            batting_side = latest_inn["batting"]
            members = latest["teams"][batting_side]["members"]

            eligible = [
                p for p in members
                if not p.get("is_ai")
            ]

            if len(eligible) == 1:
                await matches.update_one(
                    {
                        "_id": latest["_id"],
                        "current.striker_id": user_id,
                        "current.non_striker_id": None
                    },
                    {
                        "$set": {
                            "current.non_striker_id": user_id
                        }
                    }
                )
            else:
                await callback.message.answer(
                    "🏏 <b>Choose Opening Non-Striker:</b>",
                    reply_markup=_player_keyboard(
                        "non_striker",
                        match_id,
                        members,
                        [user_id]
                    )
                )

        await _maybe_finish_opening_selection(
            callback.message,
            latest["_id"]
        )
        return

    # Normal wicket / over-change selection.
    if role == "striker":
        # New batter is always assigned as STRIKER.
        # Existing non-striker is kept unchanged.
        if current.get("non_striker_id") is None:
            batting_side = latest_inn["batting"]
            members = latest["teams"][batting_side]["members"]

            await callback.message.answer(
                "🏏 Choose Non-Striker:",
                reply_markup=_player_keyboard(
                    "non_striker",
                    match_id,
                    members,
                    [user_id]
                )
            )
            return

        # If wicket happened on the last ball of the over,
        # select the next bowler before resuming.
        if latest.get("needs_new_bowler"):
            bowling_side = latest_inn["bowling"]
            members = latest["teams"][bowling_side]["members"]

            await callback.message.answer(
                "⚾ Bowling captain: Choose the next over's bowler:",
                reply_markup=_player_keyboard(
                    "bowler",
                    match_id,
                    members,
                    [current.get("bowler_id")]
                )
            )

            await matches.update_one(
                {"_id": latest["_id"]},
                {"$unset": {"needs_new_bowler": ""}}
            )
            return

    elif role == "bowler":
        await matches.update_one(
            {"_id": latest["_id"]},
            {"$unset": {"needs_new_bowler": ""}}
        )

    # Reload latest state after all changes.
    latest = await matches.find_one({"_id": latest["_id"]})

    # Resume automatically after the new batter or bowler is confirmed.
    if latest:
        await _announce_next_ball(callback.message, latest)


async def _announce_next_ball(message, match):
    inn = match["innings"][match["current_innings"] - 1]
    current = match.get("current", {})

    striker = _member_any(
        match,
        current.get("striker_id")
    )[0]

    non_striker = _member_any(
        match,
        current.get("non_striker_id")
    )[0]

    bowler = _member_any(
        match,
        current.get("bowler_id")
    )[0]

    if not all((striker, non_striker, bowler)):
        await message.answer(
            "Player selection is incomplete."
        )
        return

    bot_user = await message.bot.get_me()

    deep_link = (
        f"https://t.me/{bot_user.username}"
        f"?start=bowl_{match['_id']}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🎯 Go to Bowl DM",
                url=deep_link
            )
        ]]
    )

    balls = inn["legal_balls"]

    batter_stats = inn.get(
        "batters", {}
    ).get(
        str(striker["user_id"]), {}
    )

    await message.answer(
        f"⚾ {mention(bowler['user_id'], bowler['name'])} bowl now! "
        f"[{balls // 6}.{balls % 6} {inn['wickets']}wkt]\n"
        f"🏏 {mention(striker['user_id'], striker['name'])} get ready! "
        f"[{batter_stats.get('runs', 0)}"
        f"({batter_stats.get('balls', 0)}b)]",
        reply_markup=keyboard
    )


@router.message(CommandStart())
async def bowl_deep_link(
    message: Message,
    command: CommandObject
):
    args = command.args or ""

    if not args.startswith("bowl_"):
        return

    match_id = args.removeprefix("bowl_")

    try:
        match = await matches.find_one({
            "_id": ObjectId(match_id),
            "status": "live"
        })
    except Exception:
        match = None

    if not match or message.chat.type != "private":
        await message.answer(
            "No active bowling turn found."
        )
        return

    if (
        message.from_user.id
        != match.get("current", {}).get("bowler_id")
    ):
        await message.answer(
            "❌ It is not your bowling turn."
        )
        return

    inn = match["innings"][match["current_innings"] - 1]
    current = match.get("current", {})

    striker = _member_any(
        match,
        current.get("striker_id")
    )[0]

    if not striker:
        await message.answer(
            "Opening batter is not selected yet. "
            "Ask the Host/Captain to finish player selection."
        )
        return

    turn_id = (
        f"{match['_id']}:{inn['number']}:"
        f"{inn['legal_balls']}:"
        f"{current.get('bowler_id')}:"
        f"{uuid.uuid4().hex[:10]}"
    )

    deadline = (
        datetime.now(timezone.utc)
        + timedelta(seconds=60)
    )

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "current.turn_id": turn_id,
                "current.bowler_deadline": deadline,
                "current.pending_bowl": None,
                "current.timeout": False
            }
        }
    )

    await message.answer(
        "🎯 <b>YOUR TURN TO BOWL!</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🏏 Batter: {mention(striker['user_id'], striker['name'])}\n"
        "🔢 Send 1-6 (NOT 0!)\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🎳 {inn['legal_balls'] // 6}."
        f"{inn['legal_balls'] % 6} "
        f"of {match['settings'].get('overs', '?')}\n"
        "⏱ 1 minute!"
    )

    asyncio.create_task(
        _bowler_timeout(
            message.bot,
            match["_id"],
            match["chat_id"],
            turn_id
        )
    )


async def resume_pending_timeouts(bot):
    """Restore timeout tasks after a Railway/container restart."""
    cursor = matches.find({
        "status": "live",
        "current.bowler_deadline": {"$ne": None},
        "current.turn_id": {"$ne": None}
    })

    async for match in cursor:
        current = match.get("current", {})

        if (
            current.get("pending_bowl") is None
            and not current.get("timeout")
        ):
            asyncio.create_task(
                _bowler_timeout(
                    bot,
                    match["_id"],
                    match["chat_id"],
                    current["turn_id"]
                )
            )


async def _bowler_timeout(
    bot,
    match_id,
    chat_id,
    turn_id
):
    """Pause the delivery at its persisted deadline."""
    snapshot = await matches.find_one({
        "_id": match_id,
        "status": "live",
        "current.turn_id": turn_id
    })

    if not snapshot:
        return

    deadline = snapshot.get(
        "current", {}
    ).get("bowler_deadline")

    if not deadline:
        return

    if deadline.tzinfo is None:
        deadline = deadline.replace(
            tzinfo=timezone.utc
        )

    await asyncio.sleep(
        max(
            0,
            (
                deadline - datetime.now(timezone.utc)
            ).total_seconds()
        )
    )

    match = await matches.find_one({
        "_id": match_id,
        "status": "live",
        "current.turn_id": turn_id
    })

    if not match:
        return

    current = match.get("current", {})

    if (
        current.get("pending_bowl") is not None
        or current.get("timeout")
    ):
        return

    result = await matches.update_one(
        {
            "_id": match_id,
            "status": "live",
            "current.turn_id": turn_id,
            "current.pending_bowl": None,
            "current.timeout": False
        },
        {
            "$set": {
                "current.timeout": True,
                "current.bowler_deadline": None
            }
        }
    )

    if result.modified_count != 1:
        return

    try:
        inn = match["innings"][
            match["current_innings"] - 1
        ]

        side = inn["bowling"]

        keyboard = _player_keyboard(
            "bowler",
            str(match_id),
            match["teams"][side]["members"],
            [current.get("bowler_id")]
        )

        await bot.send_message(
            chat_id,
            "⏱ <b>BOWLER TIMEOUT!</b>\n"
            "No ball was counted and the score is unchanged.\n"
            "Host or Bowling Captain: choose another bowler.",
            reply_markup=keyboard
        )

    except Exception as exc:
        print(
            f"Bowler timeout notification failed: {exc}"
        )


@router.message(
    F.chat.type == "private",
    F.text.regexp(r"^[0-9]+$")
)
async def bowler_number_dm(message: Message):
    value = int(message.text.strip())

    if value not in range(1, 7):
        await message.answer(
            "❌ Send a number from 1 to 6 only. "
            "0 is not allowed."
        )
        return

    match = await matches.find_one(
        {
            "status": "live",
            "current.bowler_id": message.from_user.id
        },
        sort=[("created_at", -1)]
    )

    if not match:
        await message.answer(
            "No active bowling turn assigned to you."
        )
        return

    current = match.get("current", {})
    deadline = current.get("bowler_deadline")

    if (
        current.get("timeout")
        or not deadline
        or datetime.now(timezone.utc) > deadline
    ):
        await message.answer(
            "⏱ Your bowling time expired. "
            "Ask the Host/Captain to select the next bowler."
        )
        return

    if current.get("pending_bowl") is not None:
        await message.answer(
            "A bowling number has already been submitted "
            "for this delivery."
        )
        return

    result = await matches.update_one(
        {
            "_id": match["_id"],
            "current.turn_id": current.get("turn_id"),
            "current.pending_bowl": None,
            "current.timeout": False
        },
        {
            "$set": {
                "current.pending_bowl": value,
                "current.bowler_deadline": None
            }
        }
    )

    if result.modified_count != 1:
        await message.answer(
            "This bowling turn is no longer active."
        )
        return

    await message.answer(
        "✅ BOWLED!\n"
        "Tap GO TO GROUP to return to the match.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="GO TO GROUP",
                    url=(
                        "https://t.me/c/"
                        f"{str(match['chat_id']).replace('-100', '')}"
                    )
                )
            ]]
        )
    )

    try:
        await message.bot.send_message(
            match["chat_id"],
            "✅ <b>Bowler sent!</b>\n"
            "🏏 Batter, type 1-6 in group!"
        )
    except Exception:
        pass

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.regexp(r"^[1-6]$")
)
async def batter_number_group(message: Message):
    match = await _active(message.chat.id)

    if (
        not match
        or not match.get("current", {}).get("pending_bowl")
    ):
        return

    inn_index = match["current_innings"] - 1
    inn = match["innings"][inn_index]
    current = match.get("current", {})

    if message.from_user.id != current.get("striker_id"):
        return

    batter_number = int(message.text)
    submitted_number = batter_number
    bowler_number = int(current["pending_bowl"])

    batter = _member_any(
        match,
        current["striker_id"]
    )[0]

    bowler = _member_any(
        match,
        current["bowler_id"]
    )[0]

    if not batter or not bowler:
        await message.answer(
            "❌ Batter or bowler selection is missing."
        )
        return

    batter_key = str(batter["user_id"])
    bowler_key = str(bowler["user_id"])

    bat = inn.setdefault(
        "batters", {}
    ).setdefault(
        batter_key,
        {
            "name": batter["name"],
            "runs": 0,
            "balls": 0,
            "fours": 0,
            "sixes": 0,
            "out": False
        }
    )

    bowl = inn.setdefault(
        "bowlers", {}
    ).setdefault(
        bowler_key,
        {
            "name": bowler["name"],
            "runs": 0,
            "wickets": 0,
            "legal_balls": 0,
            "maidens": 0
        }
    )

    inn.setdefault(
        "extras",
        {
            "wides": 0,
            "no_balls": 0,
            "byes": 0,
            "leg_byes": 0,
            "penalty": 0
        }
    )

    is_wicket = bowler_number == batter_number

    is_no_ball = (
        bool(match["settings"].get("no_ball"))
        and not is_wicket
    )

    legal_ball_counted = False

    # Power Play resolution.
    if (
        not is_no_ball
        and match["settings"].get("power_play")
    ):
        completed_overs = inn["legal_balls"] // 6
        total_overs = int(
            match["settings"].get("overs", 1)
        )

        if completed_overs < 2 and batter_number == 6:
            is_wicket = (
                random.random()
                >= POWERPLAY_EARLY_SIX_CHANCE
            )

        elif (
            completed_overs >= max(0, total_overs - 2)
            and batter_number in (4, 6)
        ):
            if (
                random.random()
                >= POWERPLAY_LATE_BOUNDARY_CHANCE
            ):
                batter_number = 1

        is_no_ball = (
            bool(match["settings"].get("no_ball"))
            and not is_wicket
            and bowler_number != submitted_number
        )

    result_key = (
        "wicket"
        if is_wicket
        else (
            "no_ball"
            if is_no_ball
            else {
                1: "run_1",
                2: "run_2",
                3: "run_3",
                4: "four",
                5: "run_5",
                6: "six"
            }[batter_number]
        )
    )

    text = ""

    if is_wicket:
        bat["balls"] += 1
        bat["out"] = True

        inn["wickets"] += 1
        bowl["wickets"] += 1
        bowl["legal_balls"] += 1
        inn["legal_balls"] += 1
        legal_ball_counted = True

        inn["fall_of_wickets"].append({
            "score": inn["runs"],
            "wicket": inn["wickets"],
            "over": (
                f"{inn['legal_balls'] // 6}."
                f"{inn['legal_balls'] % 6}"
            ),
            "name": batter["name"]
        })

        if (
            inn.get("hat_trick_bowler_id")
            == bowler["user_id"]
        ):
            inn["hat_trick_streak"] = (
                inn.get("hat_trick_streak", 0) + 1
            )
        else:
            inn["hat_trick_bowler_id"] = bowler["user_id"]
            inn["hat_trick_streak"] = 1

        inn.setdefault(
            "partnership_history", []
        ).append({
            "runs": inn.get("partnership", 0),
            "balls": inn.get("partnership_balls", 0),
            "wicket": inn["wickets"],
            "batters": [
                inn.get("batters", {}).get(
                    str(current.get("striker_id")), {}
                ).get("name", "Batter"),
                inn.get("batters", {}).get(
                    str(current.get("non_striker_id")), {}
                ).get("name", "Batter")
            ]
        })

        inn["partnership"] = 0
        inn["partnership_balls"] = 0
        inn["partnership_milestones"] = []

        text = (
            "💥 <b>WICKET!</b>\n"
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"played {batter_number}\n"
            "DISMISSED! Great bowling! 🎯\n"
            f"{mention(batter['user_id'], batter['name'])} "
            "DISMISSED!"
        )

        if inn["hat_trick_streak"] == 3:
            await send_event_media(message, "hat_trick")

            await message.answer(
                "🎩 <b>HAT-TRICK!</b>\n"
                f"⚾ {mention(bowler['user_id'], bowler['name'])} "
                "takes THREE wickets in a row! 🔥"
            )

            inn["hat_trick_streak"] = 0

    else:
        runs = batter_number

        bat["runs"] += runs

        if not is_no_ball:
            bat["balls"] += 1

        if runs == 4:
            bat["fours"] += 1

        if runs == 6:
            bat["sixes"] += 1

        inn["runs"] += runs
        bowl["runs"] += runs

        inn["partnership"] = (
            inn.get("partnership", 0) + runs
        )

        if not is_no_ball:
            inn["partnership_balls"] = (
                inn.get("partnership_balls", 0) + 1
            )

        if is_no_ball:
            inn["extras"]["no_balls"] += 1
            inn["runs"] += 1
            bowl["runs"] += 1
            inn["partnership"] += 1

        else:
            inn["legal_balls"] += 1
            bowl["legal_balls"] += 1
            legal_ball_counted = True

        if not is_no_ball:
            inn["hat_trick_streak"] = 0
            inn["hat_trick_bowler_id"] = None

        text = (
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"scored {runs} RUNS!"
        )

        if runs == 4:
            text += "\n🎯 FOUR!"

        if runs == 6:
            text += "\n🚀 SIX!"

        if is_no_ball:
            text += "\n🚫 NO-BALL!"

        if runs % 2 == 1:
            (
                current["striker_id"],
                current["non_striker_id"]
            ) = (
                current["non_striker_id"],
                current["striker_id"]
            )

    await send_event_media(message, result_key)

    await message.answer(
        text
        + f"\n\n📊 Score: {inn['runs']}/{inn['wickets']} "
        f"({inn['legal_balls'] // 6}."
        f"{inn['legal_balls'] % 6} ov)"
    )

    current.pop("pending_bowl", None)
    current.pop("bowler_deadline", None)
    current.pop("timeout", None)

    # Batter milestones.
    milestone_map = {
        50: "fifty",
        100: "hundred",
        150: "one_fifty",
        200: "two_hundred"
    }

    achieved = inn.setdefault(
        "player_milestones", {}
    ).setdefault(
        batter_key, []
    )

    for threshold, media_key in milestone_map.items():
        if (
            bat["runs"] >= threshold
            and threshold not in achieved
        ):
            achieved.append(threshold)

            await send_event_media(
                message,
                media_key
            )

            label = {
                50: "HALF CENTURY!",
                100: "CENTURY!",
                150: "150 RUNS!",
                200: "DOUBLE CENTURY!"
            }[threshold]

            await message.answer(
                f"🎉 <b>{label}</b>\n"
                f"🏏 {mention(batter['user_id'], batter['name'])} "
                f"reaches {threshold} runs! 🔥"
            )

    # Partnership milestones.
    pms = inn.setdefault(
        "partnership_milestones", []
    )

    for threshold in (50, 100, 150):
        if (
            inn.get("partnership", 0) >= threshold
            and threshold not in pms
        ):
            pms.append(threshold)

            await send_event_media(
                message,
                f"partnership_{threshold}"
            )

            non_striker = _member_any(
                match,
                current.get("non_striker_id")
            )[0]

            if non_striker:
                await message.answer(
                    f"🤝 <b>{threshold} RUNS PARTNERSHIP!</b>\n"
                    f"🏏 {mention(batter['user_id'], batter['name'])}\n"
                    f"🏏 {mention(non_striker['user_id'], non_striker['name'])}\n"
                    "Brilliant partnership! 🔥"
                )

    # End of over and strike rotation.
    over_ended = (
        legal_ball_counted
        and inn["legal_balls"] > 0
        and inn["legal_balls"] % 6 == 0
    )

    if over_ended:
        (
            current["striker_id"],
            current["non_striker_id"]
        ) = (
            current["non_striker_id"],
            current["striker_id"]
        )

        await message.answer(
            _over_summary(inn, match)
        )

    match["innings"][inn_index] = inn

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "innings": match["innings"],
                "current": current
            }
        }
    )

    # Wicket: show batting roster and bring-back buttons.
    if is_wicket:
        side = inn["batting"]
        rows = []

        for player in match["teams"][side]["members"]:
            player_stats = inn.get(
                "batters", {}
            ).get(
                str(player["user_id"]), {}
            )

            if player_stats.get("out"):
                rows.append([
                    InlineKeyboardButton(
                        text=(
                            f"↩️ Bring Back "
                            f"{player['name'][:25]}"
                        ),
                        callback_data=(
                            f"bringback:{match['_id']}:"
                            f"{player['user_id']}"
                        )
                    )
                ])

        roster = "\n".join(
            (
                "❌ OUT"
                if inn.get("batters", {}).get(
                    str(player["user_id"]), {}
                ).get("out")
                else "🟢 IN"
            )
            + " — "
            + player["name"]
            for player in match["teams"][side]["members"]
        )

        await message.answer(
            "📋 <b>Batting Team Player Status</b>\n"
            + roster,
            reply_markup=(
                InlineKeyboardMarkup(
                    inline_keyboard=rows
                )
                if rows else None
            )
        )

    # Innings end conditions.
    max_wickets = (
        len(match["teams"][inn["batting"]]["members"]) - 1
        if match["settings"].get("wickets") == "auto"
        else int(match["settings"].get("wickets", 10))
    )

    max_balls = (
        int(match["settings"].get("overs", 1)) * 6
    )

    innings_finished = (
        inn["wickets"] >= max_wickets
        or inn["legal_balls"] >= max_balls
    )

    target_reached = (
        inn.get("target") is not None
        and inn["runs"] >= inn["target"]
    )

    if (
        inn["number"] == 2
        and (innings_finished or target_reached)
    ):
        first_runs = match["innings"][0]["runs"]
        second_runs = inn["runs"]

        if second_runs == first_runs:
            winner_side, margin, tied = None, "", True

        elif second_runs > first_runs:
            remaining = max(
                0,
                len(
                    match["teams"][inn["batting"]]["members"]
                ) - 1 - inn["wickets"]
            )

            winner_side = inn["batting"]
            margin = f"by {remaining} wickets"
            tied = False

        else:
            winner_side = match["innings"][0]["batting"]
            margin = f"by {first_runs - second_runs} runs"
            tied = False

        match["innings"][inn_index] = inn

        report = _final_report(
            match,
            winner_side,
            margin,
            tied
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "status": "ended",
                    "stage": "ended",
                    "final_result": {
                        "winner": winner_side,
                        "margin": margin,
                        "tied": tied
                    },
                    "ended_at": datetime.now(timezone.utc),
                    "innings": match["innings"],
                    "current": current
                }
            }
        )

        await send_event_media(
            message,
            "match_result"
        )

        await message.answer(report)
        return

    if innings_finished:
        await send_event_media(
            message,
            "innings_break"
        )

        target = inn["runs"] + 1

        await message.answer(
            "🏁 <b>INNINGS 1 COMPLETED!</b>\n"
            f"Team {inn['bowling']} need {target} runs to win!\n"
            "🎮 Host: use /swap_innings to start Innings 2."
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "stage": "innings_break",
                    "current": current,
                    "innings": match["innings"]
                }
            }
        )
        return

    # Wicket: select a NEW STRIKER.
    # Existing non-striker stays in the non-striker position.
    if is_wicket:
        members = match["teams"][inn["batting"]]["members"]

        exclude = (
            [current.get("non_striker_id")]
            + [
                int(uid)
                for uid, stats in inn.get(
                    "batters", {}
                ).items()
                if stats.get("out")
            ]
        )

        if over_ended:
            await matches.update_one(
                {"_id": match["_id"]},
                {
                    "$set": {
                        "needs_new_bowler": True
                    }
                }
            )

        await message.answer(
            "🏏 <b>Choose the next batter (NEW STRIKER):</b>",
            reply_markup=_player_keyboard(
                "striker",
                str(match["_id"]),
                members,
                exclude
            )
        )
        return

    if over_ended:
        members = match["teams"][inn["bowling"]]["members"]

        await message.answer(
            "⚾ Bowling captain: Choose the next over's bowler:",
            reply_markup=_player_keyboard(
                "bowler",
                str(match["_id"]),
                members,
                [current.get("bowler_id")]
            )
        )
        return

    await _announce_next_ball(
        message,
        {
            **match,
            "innings": match["innings"],
            "current": current
        }
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.regexp(r"^[1-6]$")
)
async def batter_number_group(message: Message):
    match = await _active(message.chat.id)

    if (
        not match
        or not match.get("current", {}).get("pending_bowl")
    ):
        return

    inn_index = match["current_innings"] - 1
    inn = match["innings"][inn_index]
    current = match.get("current", {})

    if message.from_user.id != current.get("striker_id"):
        return

    batter_number = int(message.text)
    submitted_number = batter_number
    bowler_number = int(current["pending_bowl"])

    batter = _member_any(
        match,
        current["striker_id"]
    )[0]

    bowler = _member_any(
        match,
        current["bowler_id"]
    )[0]

    if not batter or not bowler:
        await message.answer(
            "❌ Batter or bowler selection is missing."
        )
        return

    batter_key = str(batter["user_id"])
    bowler_key = str(bowler["user_id"])

    bat = inn.setdefault(
        "batters", {}
    ).setdefault(
        batter_key,
        {
            "name": batter["name"],
            "runs": 0,
            "balls": 0,
            "fours": 0,
            "sixes": 0,
            "out": False
        }
    )

    bowl = inn.setdefault(
        "bowlers", {}
    ).setdefault(
        bowler_key,
        {
            "name": bowler["name"],
            "runs": 0,
            "wickets": 0,
            "legal_balls": 0,
            "maidens": 0
        }
    )

    inn.setdefault(
        "extras",
        {
            "wides": 0,
            "no_balls": 0,
            "byes": 0,
            "leg_byes": 0,
            "penalty": 0
        }
    )

    is_wicket = bowler_number == batter_number

    is_no_ball = (
        bool(match["settings"].get("no_ball"))
        and not is_wicket
    )

    legal_ball_counted = False

    # Power Play resolution.
    if (
        not is_no_ball
        and match["settings"].get("power_play")
    ):
        completed_overs = inn["legal_balls"] // 6
        total_overs = int(
            match["settings"].get("overs", 1)
        )

        if completed_overs < 2 and batter_number == 6:
            is_wicket = (
                random.random()
                >= POWERPLAY_EARLY_SIX_CHANCE
            )

        elif (
            completed_overs >= max(0, total_overs - 2)
            and batter_number in (4, 6)
        ):
            if (
                random.random()
                >= POWERPLAY_LATE_BOUNDARY_CHANCE
            ):
                batter_number = 1

        is_no_ball = (
            bool(match["settings"].get("no_ball"))
            and not is_wicket
            and bowler_number != submitted_number
        )

    result_key = (
        "wicket"
        if is_wicket
        else (
            "no_ball"
            if is_no_ball
            else {
                1: "run_1",
                2: "run_2",
                3: "run_3",
                4: "four",
                5: "run_5",
                6: "six"
            }[batter_number]
        )
    )

    text = ""

    if is_wicket:
        bat["balls"] += 1
        bat["out"] = True

        inn["wickets"] += 1
        bowl["wickets"] += 1
        bowl["legal_balls"] += 1
        inn["legal_balls"] += 1
        legal_ball_counted = True

        inn["fall_of_wickets"].append({
            "score": inn["runs"],
            "wicket": inn["wickets"],
            "over": (
                f"{inn['legal_balls'] // 6}."
                f"{inn['legal_balls'] % 6}"
            ),
            "name": batter["name"]
        })

        if (
            inn.get("hat_trick_bowler_id")
            == bowler["user_id"]
        ):
            inn["hat_trick_streak"] = (
                inn.get("hat_trick_streak", 0) + 1
            )
        else:
            inn["hat_trick_bowler_id"] = bowler["user_id"]
            inn["hat_trick_streak"] = 1

        inn.setdefault(
            "partnership_history", []
        ).append({
            "runs": inn.get("partnership", 0),
            "balls": inn.get("partnership_balls", 0),
            "wicket": inn["wickets"],
            "batters": [
                inn.get("batters", {}).get(
                    str(current.get("striker_id")), {}
                ).get("name", "Batter"),
                inn.get("batters", {}).get(
                    str(current.get("non_striker_id")), {}
                ).get("name", "Batter")
            ]
        })

        inn["partnership"] = 0
        inn["partnership_balls"] = 0
        inn["partnership_milestones"] = []

        text = (
            "💥 <b>WICKET!</b>\n"
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"played {batter_number}\n"
            "DISMISSED! Great bowling! 🎯\n"
            f"{mention(batter['user_id'], batter['name'])} "
            "DISMISSED!"
        )

        if inn["hat_trick_streak"] == 3:
            await send_event_media(message, "hat_trick")

            await message.answer(
                "🎩 <b>HAT-TRICK!</b>\n"
                f"⚾ {mention(bowler['user_id'], bowler['name'])} "
                "takes THREE wickets in a row! 🔥"
            )

            inn["hat_trick_streak"] = 0

    else:
        runs = batter_number

        bat["runs"] += runs

        if not is_no_ball:
            bat["balls"] += 1

        if runs == 4:
            bat["fours"] += 1

        if runs == 6:
            bat["sixes"] += 1

        inn["runs"] += runs
        bowl["runs"] += runs

        inn["partnership"] = (
            inn.get("partnership", 0) + runs
        )

        if not is_no_ball:
            inn["partnership_balls"] = (
                inn.get("partnership_balls", 0) + 1
            )

        if is_no_ball:
            inn["extras"]["no_balls"] += 1
            inn["runs"] += 1
            bowl["runs"] += 1
            inn["partnership"] += 1

        else:
            inn["legal_balls"] += 1
            bowl["legal_balls"] += 1
            legal_ball_counted = True

        if not is_no_ball:
            inn["hat_trick_streak"] = 0
            inn["hat_trick_bowler_id"] = None

        text = (
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"scored {runs} RUNS!"
        )

        if runs == 4:
            text += "\n🎯 FOUR!"

        if runs == 6:
            text += "\n🚀 SIX!"

        if is_no_ball:
            text += "\n🚫 NO-BALL!"

        if runs % 2 == 1:
            (
                current["striker_id"],
                current["non_striker_id"]
            ) = (
                current["non_striker_id"],
                current["striker_id"]
            )

    await send_event_media(message, result_key)

    await message.answer(
        text
        + f"\n\n📊 Score: {inn['runs']}/{inn['wickets']} "
        f"({inn['legal_balls'] // 6}."
        f"{inn['legal_balls'] % 6} ov)"
    )

    current.pop("pending_bowl", None)
    current.pop("bowler_deadline", None)
    current.pop("timeout", None)

    # Batter milestones.
    milestone_map = {
        50: "fifty",
        100: "hundred",
        150: "one_fifty",
        200: "two_hundred"
    }

    achieved = inn.setdefault(
        "player_milestones", {}
    ).setdefault(
        batter_key, []
    )

    for threshold, media_key in milestone_map.items():
        if (
            bat["runs"] >= threshold
            and threshold not in achieved
        ):
            achieved.append(threshold)

            await send_event_media(
                message,
                media_key
            )

            label = {
                50: "HALF CENTURY!",
                100: "CENTURY!",
                150: "150 RUNS!",
                200: "DOUBLE CENTURY!"
            }[threshold]

            await message.answer(
                f"🎉 <b>{label}</b>\n"
                f"🏏 {mention(batter['user_id'], batter['name'])} "
                f"reaches {threshold} runs! 🔥"
            )

    # Partnership milestones.
    pms = inn.setdefault(
        "partnership_milestones", []
    )

    for threshold in (50, 100, 150):
        if (
            inn.get("partnership", 0) >= threshold
            and threshold not in pms
        ):
            pms.append(threshold)

            await send_event_media(
                message,
                f"partnership_{threshold}"
            )

            non_striker = _member_any(
                match,
                current.get("non_striker_id")
            )[0]

            if non_striker:
                await message.answer(
                    f"🤝 <b>{threshold} RUNS PARTNERSHIP!</b>\n"
                    f"🏏 {mention(batter['user_id'], batter['name'])}\n"
                    f"🏏 {mention(non_striker['user_id'], non_striker['name'])}\n"
                    "Brilliant partnership! 🔥"
                )

    # End of over and strike rotation.
    over_ended = (
        legal_ball_counted
        and inn["legal_balls"] > 0
        and inn["legal_balls"] % 6 == 0
    )

    if over_ended:
        (
            current["striker_id"],
            current["non_striker_id"]
        ) = (
            current["non_striker_id"],
            current["striker_id"]
        )

        await message.answer(
            _over_summary(inn, match)
        )

    match["innings"][inn_index] = inn

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "innings": match["innings"],
                "current": current
            }
        }
    )

    # Wicket: show batting roster and bring-back buttons.
    if is_wicket:
        side = inn["batting"]
        rows = []

        for player in match["teams"][side]["members"]:
            player_stats = inn.get(
                "batters", {}
            ).get(
                str(player["user_id"]), {}
            )

            if player_stats.get("out"):
                rows.append([
                    InlineKeyboardButton(
                        text=(
                            f"↩️ Bring Back "
                            f"{player['name'][:25]}"
                        ),
                        callback_data=(
                            f"bringback:{match['_id']}:"
                            f"{player['user_id']}"
                        )
                    )
                ])

        roster = "\n".join(
            (
                "❌ OUT"
                if inn.get("batters", {}).get(
                    str(player["user_id"]), {}
                ).get("out")
                else "🟢 IN"
            )
            + " — "
            + player["name"]
            for player in match["teams"][side]["members"]
        )

        await message.answer(
            "📋 <b>Batting Team Player Status</b>\n"
            + roster,
            reply_markup=(
                InlineKeyboardMarkup(
                    inline_keyboard=rows
                )
                if rows else None
            )
        )

    # Innings end conditions.
    max_wickets = (
        len(match["teams"][inn["batting"]]["members"]) - 1
        if match["settings"].get("wickets") == "auto"
        else int(match["settings"].get("wickets", 10))
    )

    max_balls = (
        int(match["settings"].get("overs", 1)) * 6
    )

    innings_finished = (
        inn["wickets"] >= max_wickets
        or inn["legal_balls"] >= max_balls
    )

    target_reached = (
        inn.get("target") is not None
        and inn["runs"] >= inn["target"]
    )

    if (
        inn["number"] == 2
        and (innings_finished or target_reached)
    ):
        first_runs = match["innings"][0]["runs"]
        second_runs = inn["runs"]

        if second_runs == first_runs:
            winner_side, margin, tied = None, "", True

        elif second_runs > first_runs:
            remaining = max(
                0,
                len(
                    match["teams"][inn["batting"]]["members"]
                ) - 1 - inn["wickets"]
            )

            winner_side = inn["batting"]
            margin = f"by {remaining} wickets"
            tied = False

        else:
            winner_side = match["innings"][0]["batting"]
            margin = f"by {first_runs - second_runs} runs"
            tied = False

        match["innings"][inn_index] = inn

        report = _final_report(
            match,
            winner_side,
            margin,
            tied
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "status": "ended",
                    "stage": "ended",
                    "final_result": {
                        "winner": winner_side,
                        "margin": margin,
                        "tied": tied
                    },
                    "ended_at": datetime.now(timezone.utc),
                    "innings": match["innings"],
                    "current": current
                }
            }
        )

        await send_event_media(
            message,
            "match_result"
        )

        await message.answer(report)
        return

    if innings_finished:
        await send_event_media(
            message,
            "innings_break"
        )

        target = inn["runs"] + 1

        await message.answer(
            "🏁 <b>INNINGS 1 COMPLETED!</b>\n"
            f"Team {inn['bowling']} need {target} runs to win!\n"
            "🎮 Host: use /swap_innings to start Innings 2."
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "stage": "innings_break",
                    "current": current,
                    "innings": match["innings"]
                }
            }
        )
        return

    # Wicket: select a NEW STRIKER.
    # Existing non-striker stays in the non-striker position.
    if is_wicket:
        members = match["teams"][inn["batting"]]["members"]

        exclude = (
            [current.get("non_striker_id")]
            + [
                int(uid)
                for uid, stats in inn.get(
                    "batters", {}
                ).items()
                if stats.get("out")
            ]
        )

        if over_ended:
            await matches.update_one(
                {"_id": match["_id"]},
                {
                    "$set": {
                        "needs_new_bowler": True
                    }
                }
            )

        await message.answer(
            "🏏 <b>Choose the next batter (NEW STRIKER):</b>",
            reply_markup=_player_keyboard(
                "striker",
                str(match["_id"]),
                members,
                exclude
            )
        )
        return

    if over_ended:
        members = match["teams"][inn["bowling"]]["members"]

        await message.answer(
            "⚾ Bowling captain: Choose the next over's bowler:",
            reply_markup=_player_keyboard(
                "bowler",
                str(match["_id"]),
                members,
                [current.get("bowler_id")]
            )
        )
        return

    await _announce_next_ball(
        message,
        {
            **match,
            "innings": match["innings"],
            "current": current
        }
    )

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.regexp(r"^[1-6]$")
)
async def batter_number_group(message: Message):
    match = await _active(message.chat.id)

    if (
        not match
        or not match.get("current", {}).get("pending_bowl")
    ):
        return

    inn_index = match["current_innings"] - 1
    inn = match["innings"][inn_index]
    current = match.get("current", {})

    if message.from_user.id != current.get("striker_id"):
        return

    batter_number = int(message.text)
    submitted_number = batter_number
    bowler_number = int(current["pending_bowl"])

    batter = _member_any(
        match,
        current["striker_id"]
    )[0]

    bowler = _member_any(
        match,
        current["bowler_id"]
    )[0]

    if not batter or not bowler:
        await message.answer(
            "❌ Batter or bowler selection is missing."
        )
        return

    batter_key = str(batter["user_id"])
    bowler_key = str(bowler["user_id"])

    bat = inn.setdefault(
        "batters", {}
    ).setdefault(
        batter_key,
        {
            "name": batter["name"],
            "runs": 0,
            "balls": 0,
            "fours": 0,
            "sixes": 0,
            "out": False
        }
    )

    bowl = inn.setdefault(
        "bowlers", {}
    ).setdefault(
        bowler_key,
        {
            "name": bowler["name"],
            "runs": 0,
            "wickets": 0,
            "legal_balls": 0,
            "maidens": 0
        }
    )

    inn.setdefault(
        "extras",
        {
            "wides": 0,
            "no_balls": 0,
            "byes": 0,
            "leg_byes": 0,
            "penalty": 0
        }
    )

    is_wicket = bowler_number == batter_number

    is_no_ball = (
        bool(match["settings"].get("no_ball"))
        and not is_wicket
    )

    legal_ball_counted = False

    # Power Play resolution.
    if (
        not is_no_ball
        and match["settings"].get("power_play")
    ):
        completed_overs = inn["legal_balls"] // 6
        total_overs = int(
            match["settings"].get("overs", 1)
        )

        if completed_overs < 2 and batter_number == 6:
            is_wicket = (
                random.random()
                >= POWERPLAY_EARLY_SIX_CHANCE
            )

        elif (
            completed_overs >= max(0, total_overs - 2)
            and batter_number in (4, 6)
        ):
            if (
                random.random()
                >= POWERPLAY_LATE_BOUNDARY_CHANCE
            ):
                batter_number = 1

        is_no_ball = (
            bool(match["settings"].get("no_ball"))
            and not is_wicket
            and bowler_number != submitted_number
        )

    result_key = (
        "wicket"
        if is_wicket
        else (
            "no_ball"
            if is_no_ball
            else {
                1: "run_1",
                2: "run_2",
                3: "run_3",
                4: "four",
                5: "run_5",
                6: "six"
            }[batter_number]
        )
    )

    text = ""

    if is_wicket:
        bat["balls"] += 1
        bat["out"] = True

        inn["wickets"] += 1
        bowl["wickets"] += 1
        bowl["legal_balls"] += 1
        inn["legal_balls"] += 1
        legal_ball_counted = True

        inn["fall_of_wickets"].append({
            "score": inn["runs"],
            "wicket": inn["wickets"],
            "over": (
                f"{inn['legal_balls'] // 6}."
                f"{inn['legal_balls'] % 6}"
            ),
            "name": batter["name"]
        })

        if (
            inn.get("hat_trick_bowler_id")
            == bowler["user_id"]
        ):
            inn["hat_trick_streak"] = (
                inn.get("hat_trick_streak", 0) + 1
            )
        else:
            inn["hat_trick_bowler_id"] = bowler["user_id"]
            inn["hat_trick_streak"] = 1

        inn.setdefault(
            "partnership_history", []
        ).append({
            "runs": inn.get("partnership", 0),
            "balls": inn.get("partnership_balls", 0),
            "wicket": inn["wickets"],
            "batters": [
                inn.get("batters", {}).get(
                    str(current.get("striker_id")), {}
                ).get("name", "Batter"),
                inn.get("batters", {}).get(
                    str(current.get("non_striker_id")), {}
                ).get("name", "Batter")
            ]
        })

        inn["partnership"] = 0
        inn["partnership_balls"] = 0
        inn["partnership_milestones"] = []

        text = (
            "💥 <b>WICKET!</b>\n"
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"played {batter_number}\n"
            "DISMISSED! Great bowling! 🎯\n"
            f"{mention(batter['user_id'], batter['name'])} "
            "DISMISSED!"
        )

        if inn["hat_trick_streak"] == 3:
            await send_event_media(message, "hat_trick")

            await message.answer(
                "🎩 <b>HAT-TRICK!</b>\n"
                f"⚾ {mention(bowler['user_id'], bowler['name'])} "
                "takes THREE wickets in a row! 🔥"
            )

            inn["hat_trick_streak"] = 0

    else:
        runs = batter_number

        bat["runs"] += runs

        if not is_no_ball:
            bat["balls"] += 1

        if runs == 4:
            bat["fours"] += 1

        if runs == 6:
            bat["sixes"] += 1

        inn["runs"] += runs
        bowl["runs"] += runs

        inn["partnership"] = (
            inn.get("partnership", 0) + runs
        )

        if not is_no_ball:
            inn["partnership_balls"] = (
                inn.get("partnership_balls", 0) + 1
            )

        if is_no_ball:
            inn["extras"]["no_balls"] += 1
            inn["runs"] += 1
            bowl["runs"] += 1
            inn["partnership"] += 1

        else:
            inn["legal_balls"] += 1
            bowl["legal_balls"] += 1
            legal_ball_counted = True

        if not is_no_ball:
            inn["hat_trick_streak"] = 0
            inn["hat_trick_bowler_id"] = None

        text = (
            f"🏏 {mention(batter['user_id'], batter['name'])} "
            f"scored {runs} RUNS!"
        )

        if runs == 4:
            text += "\n🎯 FOUR!"

        if runs == 6:
            text += "\n🚀 SIX!"

        if is_no_ball:
            text += "\n🚫 NO-BALL!"

        if runs % 2 == 1:
            (
                current["striker_id"],
                current["non_striker_id"]
            ) = (
                current["non_striker_id"],
                current["striker_id"]
            )

    await send_event_media(message, result_key)

    await message.answer(
        text
        + f"\n\n📊 Score: {inn['runs']}/{inn['wickets']} "
        f"({inn['legal_balls'] // 6}."
        f"{inn['legal_balls'] % 6} ov)"
    )

    current.pop("pending_bowl", None)
    current.pop("bowler_deadline", None)
    current.pop("timeout", None)

    # Batter milestones.
    milestone_map = {
        50: "fifty",
        100: "hundred",
        150: "one_fifty",
        200: "two_hundred"
    }

    achieved = inn.setdefault(
        "player_milestones", {}
    ).setdefault(
        batter_key, []
    )

    for threshold, media_key in milestone_map.items():
        if (
            bat["runs"] >= threshold
            and threshold not in achieved
        ):
            achieved.append(threshold)

            await send_event_media(
                message,
                media_key
            )

            label = {
                50: "HALF CENTURY!",
                100: "CENTURY!",
                150: "150 RUNS!",
                200: "DOUBLE CENTURY!"
            }[threshold]

            await message.answer(
                f"🎉 <b>{label}</b>\n"
                f"🏏 {mention(batter['user_id'], batter['name'])} "
                f"reaches {threshold} runs! 🔥"
            )

    # Partnership milestones.
    pms = inn.setdefault(
        "partnership_milestones", []
    )

    for threshold in (50, 100, 150):
        if (
            inn.get("partnership", 0) >= threshold
            and threshold not in pms
        ):
            pms.append(threshold)

            await send_event_media(
                message,
                f"partnership_{threshold}"
            )

            non_striker = _member_any(
                match,
                current.get("non_striker_id")
            )[0]

            if non_striker:
                await message.answer(
                    f"🤝 <b>{threshold} RUNS PARTNERSHIP!</b>\n"
                    f"🏏 {mention(batter['user_id'], batter['name'])}\n"
                    f"🏏 {mention(non_striker['user_id'], non_striker['name'])}\n"
                    "Brilliant partnership! 🔥"
                )

    # End of over and strike rotation.
    over_ended = (
        legal_ball_counted
        and inn["legal_balls"] > 0
        and inn["legal_balls"] % 6 == 0
    )

    if over_ended:
        (
            current["striker_id"],
            current["non_striker_id"]
        ) = (
            current["non_striker_id"],
            current["striker_id"]
        )

        await message.answer(
            _over_summary(inn, match)
        )

    match["innings"][inn_index] = inn

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                "innings": match["innings"],
                "current": current
            }
        }
    )

    # Wicket: show batting roster and bring-back buttons.
    if is_wicket:
        side = inn["batting"]
        rows = []

        for player in match["teams"][side]["members"]:
            player_stats = inn.get(
                "batters", {}
            ).get(
                str(player["user_id"]), {}
            )

            if player_stats.get("out"):
                rows.append([
                    InlineKeyboardButton(
                        text=(
                            f"↩️ Bring Back "
                            f"{player['name'][:25]}"
                        ),
                        callback_data=(
                            f"bringback:{match['_id']}:"
                            f"{player['user_id']}"
                        )
                    )
                ])

        roster = "\n".join(
            (
                "❌ OUT"
                if inn.get("batters", {}).get(
                    str(player["user_id"]), {}
                ).get("out")
                else "🟢 IN"
            )
            + " — "
            + player["name"]
            for player in match["teams"][side]["members"]
        )

        await message.answer(
            "📋 <b>Batting Team Player Status</b>\n"
            + roster,
            reply_markup=(
                InlineKeyboardMarkup(
                    inline_keyboard=rows
                )
                if rows else None
            )
        )

    # Innings end conditions.
    max_wickets = (
        len(match["teams"][inn["batting"]]["members"]) - 1
        if match["settings"].get("wickets") == "auto"
        else int(match["settings"].get("wickets", 10))
    )

    max_balls = (
        int(match["settings"].get("overs", 1)) * 6
    )

    innings_finished = (
        inn["wickets"] >= max_wickets
        or inn["legal_balls"] >= max_balls
    )

    target_reached = (
        inn.get("target") is not None
        and inn["runs"] >= inn["target"]
    )

    if (
        inn["number"] == 2
        and (innings_finished or target_reached)
    ):
        first_runs = match["innings"][0]["runs"]
        second_runs = inn["runs"]

        if second_runs == first_runs:
            winner_side, margin, tied = None, "", True

        elif second_runs > first_runs:
            remaining = max(
                0,
                len(
                    match["teams"][inn["batting"]]["members"]
                ) - 1 - inn["wickets"]
            )

            winner_side = inn["batting"]
            margin = f"by {remaining} wickets"
            tied = False

        else:
            winner_side = match["innings"][0]["batting"]
            margin = f"by {first_runs - second_runs} runs"
            tied = False

        match["innings"][inn_index] = inn

        report = _final_report(
            match,
            winner_side,
            margin,
            tied
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "status": "ended",
                    "stage": "ended",
                    "final_result": {
                        "winner": winner_side,
                        "margin": margin,
                        "tied": tied
                    },
                    "ended_at": datetime.now(timezone.utc),
                    "innings": match["innings"],
                    "current": current
                }
            }
        )

        await send_event_media(
            message,
            "match_result"
        )

        await message.answer(report)
        return

    if innings_finished:
        await send_event_media(
            message,
            "innings_break"
        )

        target = inn["runs"] + 1

        await message.answer(
            "🏁 <b>INNINGS 1 COMPLETED!</b>\n"
            f"Team {inn['bowling']} need {target} runs to win!\n"
            "🎮 Host: use /swap_innings to start Innings 2."
        )

        await matches.update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "stage": "innings_break",
                    "current": current,
                    "innings": match["innings"]
                }
            }
        )
        return

    # Wicket: select a NEW STRIKER.
    # Existing non-striker stays in the non-striker position.
    if is_wicket:
        members = match["teams"][inn["batting"]]["members"]

        exclude = (
            [current.get("non_striker_id")]
            + [
                int(uid)
                for uid, stats in inn.get(
                    "batters", {}
                ).items()
                if stats.get("out")
            ]
        )

        if over_ended:
            await matches.update_one(
                {"_id": match["_id"]},
                {
                    "$set": {
                        "needs_new_bowler": True
                    }
                }
            )

        await message.answer(
            "🏏 <b>Choose the next batter (NEW STRIKER):</b>",
            reply_markup=_player_keyboard(
                "striker",
                str(match["_id"]),
                members,
                exclude
            )
        )
        return

    if over_ended:
        members = match["teams"][inn["bowling"]]["members"]

        await message.answer(
            "⚾ Bowling captain: Choose the next over's bowler:",
            reply_markup=_player_keyboard(
                "bowler",
                str(match["_id"]),
                members,
                [current.get("bowler_id")]
            )
        )
        return

    await _announce_next_ball(
        message,
        {
            **match,
            "innings": match["innings"],
            "current": current
        }
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.regexp(r"^[0-9]+$")
)
async def invalid_batter_number(message: Message):
    match = await _active(message.chat.id)

    if (
        not match
        or message.from_user.id
        != match.get("current", {}).get("striker_id")
    ):
        return

    await message.reply(
        "❌ Batter must send a number from 1 to 6 only."
    )


def _final_report(
    match,
    winner_side,
    margin,
    tied=False
):
    innings = match.get("innings", [])

    lines = [
        "🏆 <b>TFG CRICKET RIVALRY — FINAL RESULT</b>"
    ]

    if tied:
        lines.append("🤝 <b>MATCH TIED!</b>")
    else:
        lines.append(
            f"🏆 <b>TEAM {winner_side} WON {margin}!</b>"
        )

    lines.append("")

    for inn in innings:
        lines.append(
            f"🏏 Team {inn['batting']}: "
            f"{inn['runs']}/{inn['wickets']} "
            f"({inn['legal_balls'] // 6}."
            f"{inn['legal_balls'] % 6} ov)"
        )

    batters = []
    bowlers = []

    for inn in innings:
        for uid, player in inn.get(
            "batters", {}
        ).items():
            batters.append((
                player.get("name", "Player"),
                int(player.get("runs", 0)),
                int(player.get("balls", 0)),
                int(player.get("fours", 0)),
                int(player.get("sixes", 0))
            ))

        for uid, player in inn.get(
            "bowlers", {}
        ).items():
            balls = int(player.get("legal_balls", 0))
            runs = int(player.get("runs", 0))
            wickets = int(player.get("wickets", 0))

            bowlers.append((
                player.get("name", "Bowler"),
                wickets,
                runs,
                balls,
                (runs * 6 / balls if balls else 0)
            ))

    if batters:
        best_batter = max(
            batters,
            key=lambda x: x[1]
        )

        lines += [
            "",
            f"🌟 <b>BEST BATTER:</b> "
            f"{escape(best_batter[0])} — "
            f"{best_batter[1]} runs "
            f"({best_batter[2]} balls)"
        ]

        best_sr = max(
            (
                player
                for player in batters
                if player[2] >= 5
            ),
            key=lambda x: x[1] * 100 / x[2],
            default=None
        )

        if best_sr:
            lines.append(
                f"⚡ Best Strike Rate: "
                f"{escape(best_sr[0])} — "
                f"{best_sr[1] * 100 / best_sr[2]:.2f}"
            )

        most_sixes = max(
            batters,
            key=lambda x: x[4]
        )

        most_fours = max(
            batters,
            key=lambda x: x[3]
        )

        lines.append(
            f"🚀 Most Sixes: "
            f"{escape(most_sixes[0])} — {most_sixes[4]}"
        )

        lines.append(
            f"🎯 Most Fours: "
            f"{escape(most_fours[0])} — {most_fours[3]}"
        )

    if bowlers:
        best_bowler = max(
            bowlers,
            key=lambda x: (x[1], -x[4])
        )

        lines += [
            "",
            f"🎯 <b>BEST BOWLER:</b> "
            f"{escape(best_bowler[0])} — "
            f"{best_bowler[1]} wickets, "
            f"{best_bowler[2]} runs, "
            f"Econ {best_bowler[4]:.2f}"
        ]

        eligible = [
            player
            for player in bowlers
            if player[3] >= 6
        ]

        if eligible:
            best_economy = min(
                eligible,
                key=lambda x: x[4]
            )

            lines.append(
                f"🧤 Best Economy: "
                f"{escape(best_economy[0])} — "
                f"{best_economy[4]:.2f}"
            )

        most_wickets = max(
            bowlers,
            key=lambda x: x[1]
        )

        lines.append(
            f"🎳 Most Wickets: "
            f"{escape(most_wickets[0])} — "
            f"{most_wickets[1]}"
        )

        all_round = {}

        for name, runs, balls, fours, sixes in batters:
            all_round.setdefault(
                name,
                {"runs": 0, "wickets": 0}
            )["runs"] += runs

        for name, wickets, conceded, balls, econ_value in bowlers:
            all_round.setdefault(
                name,
                {"runs": 0, "wickets": 0}
            )["wickets"] += wickets

        best_ar_name, best_ar = max(
            all_round.items(),
            key=lambda item: (
                item[1]["runs"]
                + item[1]["wickets"] * 20
            )
        )

        lines.append(
            f"🏅 Best All-Rounder: "
            f"{escape(best_ar_name)} — "
            f"{best_ar['runs']} runs, "
            f"{best_ar['wickets']} wickets"
        )

        highest = max(
            batters,
            key=lambda x: x[1]
        )

        lines.append(
            f"🔥 Highest Individual Score: "
            f"{escape(highest[0])} — {highest[1]}"
        )

    partnerships = [
        part
        for inn in innings
        for part in inn.get("partnership_history", [])
    ]

    partnerships += [
        {
            "runs": inn.get("partnership", 0),
            "batters": []
        }
        for inn in innings
    ]

    if partnerships:
        best_partnership = max(
            partnerships,
            key=lambda x: x.get("runs", 0)
        )

        names = " & ".join(
            best_partnership.get("batters", [])
        )

        lines.append(
            f"🤝 Best Partnership: "
            f"{best_partnership.get('runs', 0)} runs"
            + (
                f" ({escape(names)})"
                if names else ""
            )
        )

    if batters and bowlers:
        candidates = {}

        for player in batters:
            candidates.setdefault(
                player[0],
                {
                    "runs": 0,
                    "wickets": 0,
                    "conceded": 0
                }
            )["runs"] += player[1]

        for player in bowlers:
            candidates.setdefault(
                player[0],
                {
                    "runs": 0,
                    "wickets": 0,
                    "conceded": 0
                }
            )["wickets"] += player[1]

            candidates[player[0]]["conceded"] += player[2]

        potm_name, potm = max(
            candidates.items(),
            key=lambda kv: (
                kv[1]["runs"]
                + 20 * kv[1]["wickets"]
                - kv[1]["conceded"] / 10
            )
        )

        lines += [
            "",
            f"🏅 <b>PLAYER OF THE MATCH:</b> "
            f"{escape(potm_name)}"
        ]

    lines += [
        "",
        "📋 <b>COMPLETE BATTING FIGURES</b>",
        "Player | Runs(B) | 4s | 6s | SR"
    ]

    for player in sorted(
        batters,
        key=lambda x: x[1],
        reverse=True
    ):
        sr = (
            player[1] * 100 / player[2]
            if player[2]
            else 0
        )

        lines.append(
            f"{escape(player[0])} | "
            f"{player[1]}({player[2]}) | "
            f"{player[3]} | {player[4]} | {sr:.2f}"
        )

    lines += [
        "",
        "⚾ <b>COMPLETE BOWLING FIGURES</b>",
        "Bowler | O | R | W | Econ"
    ]

    for player in bowlers:
        lines.append(
            f"{escape(player[0])} | "
            f"{player[3] // 6}.{player[3] % 6} | "
            f"{player[2]} | {player[1]} | "
            f"{player[4]:.2f}"
        )

    return "\n".join(lines)


def _over_summary(inn, match):
    lines = [
        f"📊 <b>END OF OVER {inn['legal_balls'] // 6}</b>",
        f"🏏 Team {inn['batting']}: "
        f"{inn['runs']}/{inn['wickets']} "
        f"({overs_text(inn['legal_balls'])} ov)",
        f"📈 Current Run Rate: "
        f"{run_rate(inn['runs'], inn['legal_balls']):.2f}",
        "",
        "<b>🏏 BATTING SCORECARD</b>",
        "Player | R(B) | 4s | 6s | SR | Status"
    ]

    for player in inn.get("batters", {}).values():
        sr = strike_rate(
            player.get("runs", 0),
            player.get("balls", 0)
        )

        status = (
            "OUT"
            if player.get("out")
            else "NOT OUT"
        )

        lines.append(
            f"{escape(player.get('name', 'Player'))} | "
            f"{player.get('runs', 0)}"
            f"({player.get('balls', 0)}) | "
            f"{player.get('fours', 0)} | "
            f"{player.get('sixes', 0)} | "
            f"{sr:.2f} | {status}"
        )

    lines += [
        "",
        "<b>⚾ BOWLING SCORECARD</b>",
        "Bowler | O | R | W | Econ"
    ]

    for player in inn.get("bowlers", {}).values():
        legal = int(
            player.get("legal_balls", 0)
        )

        econ_value = economy(
            player.get("runs", 0),
            legal
        )

        lines.append(
            f"{escape(player.get('name', 'Player'))} | "
            f"{overs_text(legal)} | "
            f"{player.get('runs', 0)} | "
            f"{player.get('wickets', 0)} | "
            f"{econ_value:.2f}"
        )

    extras = inn.get("extras", {})

    lines += [
        "",
        f"➕ Extras: {extras_total(extras)} "
        f"(W {extras.get('wides', 0)}, "
        f"NB {extras.get('no_balls', 0)}, "
        f"B {extras.get('byes', 0)}, "
        f"LB {extras.get('leg_byes', 0)})"
    ]

    fow = inn.get("fall_of_wickets", [])

    if fow:
        lines.append(
            "💥 Fall of wickets: "
            + ", ".join(
                f"{w.get('score')}/{w.get('wicket')} "
                f"({w.get('over')})"
                for w in fow
            )
        )

    lines.append(
        f"🤝 Current Partnership: "
        f"{inn.get('partnership', 0)} runs"
    )

    return "\n".join(lines)


@router.callback_query(F.data.startswith("bringback:"))
async def bring_back(callback: CallbackQuery):
    _, match_id, user_id = callback.data.split(":")

    match = await matches.find_one({
        "_id": ObjectId(match_id),
        "chat_id": callback.message.chat.id,
        "status": "live"
    })

    if not match:
        await callback.answer(
            "Match not active",
            show_alert=True
        )
        return

    inn = match["innings"][
        match["current_innings"] - 1
    ]

    batting_side = inn["batting"]

    if callback.from_user.id not in (
        match.get("host_id"),
        match["teams"][batting_side].get("captain_id")
    ):
        await callback.answer(
            "Only Host or Batting Captain Can Bring Back Players!",
            show_alert=True
        )
        return

    stats = inn.get(
        "batters", {}
    ).get(user_id)

    if not stats:
        await callback.answer(
            "Player has no batting record",
            show_alert=True
        )
        return

    # Restore eligibility for a later batting slot.
    stats["out"] = False
    stats["brought_back"] = True

    await matches.update_one(
        {"_id": match["_id"]},
        {
            "$set": {
                f"innings.{match['current_innings'] - 1}": inn
            }
        }
    )

    await callback.message.answer(
        f"↩️ {stats['name']} has been brought back "
        "into the batting lineup!"
    )

    await callback.answer("Player brought back")
