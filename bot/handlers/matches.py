import asyncio
import random
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.db import matches
from bot.keyboards import (host_claim_kb, join_kb, overs_kb, wickets_kb,
    yes_no_kb, weather_kb, player_select_kb, confirm_kb, toss_kb, bat_bowl_kb)
from bot.services.formatting import mention
from bot.services.event_media import send_event_media

router = Router()

async def active_match(chat_id):
    return await matches.find_one({"chat_id": chat_id, "status": {"$in": ["setup", "live"]}}, sort=[("created_at", -1)])

async def is_group_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False

async def require_host(callback_or_message, match):
    return bool(match and callback_or_message.from_user.id == match.get("host_id"))

async def require_host_or_admin(callback_or_message, match):
    if await require_host(callback_or_message, match):
        return True
    return bool(match and await is_group_admin(callback_or_message.bot, match["chat_id"], callback_or_message.from_user.id))

async def roster_text(match):
    lines = [f"🎮 Host: {mention(match['host_id'], match.get('host_name','Host'))}", "", "👥 <b>PLAYERS — JOIN NOW!</b>"]
    for side, label in (("A", "🔵 Team A"), ("B", "🔴 Team B")):
        members = match["teams"][side]["members"]
        lines.append(f"\n<b>{label} ({len(members)} Members)</b>")
        lines.extend(f"{i}. {mention(p['user_id'], p['name'])}" for i, p in enumerate(members, 1))
        if not members:
            lines.append("— Empty —")
    lines += ["", "Players: /join_a or /join_b", "Host commands: /startmatch /add_a /add_b /swap /remove_player /extend"]
    return "\n".join(lines)

@router.message(Command("newmatch"))
async def newmatch(message: Message):
    from bot.keyboards import main_menu_kb
    sent = await send_event_media(message, "welcome_banner", "🏏 <b>TFG CRICKET RIVALRY — Choose game mode:</b>")
    if not sent:
        await message.answer("🏏 <b>TFG CRICKET RIVALRY</b>\nChoose game mode:", reply_markup=main_menu_kb())
    else:
        await message.answer("Choose game mode:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "mode:team")
async def team_mode(callback: CallbackQuery):
    await callback.message.answer("👥 <b>TEAM MATCH</b>\nWho will host? (Anyone can tap)", reply_markup=host_claim_kb())
    await callback.answer()

@router.callback_query(F.data == "claim_host")
async def claim_host(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    existing = await active_match(chat_id)
    if existing:
        await callback.answer("A match is already active in this group!", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    user = callback.from_user
    doc = {
        "chat_id": chat_id, "chat_title": callback.message.chat.title or "Group",
        "status": "setup", "stage": "lobby", "host_id": user.id,
        "host_name": user.full_name, "created_at": now,
        "join_deadline": now + timedelta(minutes=5),
        "teams": {"A": {"name": "Team A", "members": [], "captain_id": None},
                  "B": {"name": "Team B", "members": [], "captain_id": None}},
        "settings": {}, "innings": [], "current_innings": 0,
    }
    result = await matches.insert_one(doc)
    doc["_id"] = result.inserted_id
    await callback.message.answer(await roster_text(doc), reply_markup=join_kb())
    await callback.answer("You are the host!")

async def join_team(message: Message, side: str):
    match = await active_match(message.chat.id)
    if not match or match.get("stage") != "lobby":
        await message.reply("❌ No open team lobby right now.")
        return
    if datetime.now(timezone.utc) > match["join_deadline"]:
        await message.reply("⏱ Joining time is over. Ask the host to use /extend.")
        return
    uid = message.from_user.id
    for s in ("A", "B"):
        if any(p["user_id"] == uid for p in match["teams"][s]["members"]):
            await message.reply("You have already joined a team.")
            return
    match["teams"][side]["members"].append({"user_id": uid, "name": message.from_user.full_name, "is_ai": False})
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer(await roster_text(match), reply_markup=join_kb())

@router.message(Command("join_a"))
async def join_a(message: Message): await join_team(message, "A")

@router.message(Command("join_b"))
async def join_b(message: Message): await join_team(message, "B")

@router.callback_query(F.data.startswith("join:"))
async def join_button(callback: CallbackQuery):
    side = callback.data.split(":")[1]
    class Proxy: pass
    proxy = Proxy(); proxy.chat = callback.message.chat; proxy.from_user = callback.from_user; proxy.reply = callback.message.answer; proxy.answer = callback.message.answer
    await join_team(proxy, side)
    await callback.answer()

@router.message(Command("extend"))
async def extend_join(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    match["join_deadline"] = datetime.now(timezone.utc) + timedelta(minutes=30)
    await matches.update_one({"_id": match["_id"]}, {"$set": {"join_deadline": match["join_deadline"]}})
    await message.reply("⏱ Joining time extended by 5 minutes!")

@router.message(Command("startmatch"))
async def startmatch(message: Message):
    match = await active_match(message.chat.id)

    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!")
        return

    if (
        len(match["teams"]["A"]["members"]) < 1
        or len(match["teams"]["B"]["members"]) < 1
    ):
        await message.reply(
            "❌ Both teams must have at least 1 player to start the match."
        )
        return

    await matches.update_one(
        {"_id": match["_id"]},
        {"$set": {"stage": "overs"}}
    )

    await message.answer(
        f"🎮 Host: {mention(match['host_id'], match['host_name'])} choose overs:",
        reply_markup=overs_kb()
    )

@router.callback_query(F.data.startswith("overs:"))
async def choose_overs(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    value = int(callback.data.split(":")[1])
    await matches.update_one({"_id": match["_id"]}, {"$set": {"settings.overs": value, "stage": "wickets"}})
    await callback.message.answer(f"✅ Overs: {value}\n🎯 Choose wickets per innings:", reply_markup=wickets_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("wickets:"))
async def choose_wickets(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    raw = callback.data.split(":")[1]
    value = "auto" if raw == "auto" else int(raw)
    await matches.update_one({"_id": match["_id"]}, {"$set": {"settings.wickets": value, "stage": "no_ball"}})
    await callback.message.answer("🎯 No-Ball Rule ON or OFF?", reply_markup=yes_no_kb("noball", "✅ No-Ball Rule ON", "🚫 No-Ball Rule OFF"))
    await callback.answer()

@router.callback_query(F.data.startswith("noball:"))
async def choose_noball(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    enabled = callback.data.endswith("on")
    await matches.update_one({"_id": match["_id"]}, {"$set": {"settings.no_ball": enabled, "stage": "weather"}})
    await callback.message.answer("🌦️ Choose match weather:", reply_markup=weather_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("weather:"))
async def choose_weather(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    weather = callback.data.split(":")[1]
    settings = match.get("settings", {})
    update = {"settings.weather": weather, "stage": "powerplay"}
    rain_note = ""
    # Default editable rain reduction: 20% for matches configured from 10 to 50 overs.
    if weather == "rainy" and 10 <= int(settings.get("overs", 0)) <= 50:
        original = int(settings["overs"])
        reduced = max(1, int(original * 0.8))
        update["settings.original_overs"] = original
        update["settings.overs"] = reduced
        rain_note = f"\n🌧️ Rain rule: overs reduced from {original} to {reduced}."
    await matches.update_one({"_id": match["_id"]}, {"$set": update})
    await callback.message.answer("🌦️ Weather selected: " + weather.title() + rain_note + "\n\n⚡ Power Play ON or OFF?", reply_markup=yes_no_kb("powerplay", "⚡ Power Play ON", "🚫 Power Play OFF"))
    await callback.answer()

@router.callback_query(F.data.startswith("powerplay:"))
async def choose_powerplay(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    enabled = callback.data.endswith("on")
    await matches.update_one({"_id": match["_id"]}, {"$set": {"settings.power_play": enabled, "stage": "captains"}})
    await callback.message.answer("👑 Host can now choose captains with /choose_captain")
    await callback.answer()

@router.message(Command("choose_captain"))
async def choose_captain(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    await matches.update_one({"_id": match["_id"]}, {"$set": {"stage": "captains"}})
    for side in ("A", "B"):
        await message.answer(f"👑 Choose Team {side} Captain:", reply_markup=player_select_kb(f"captain{side}", str(match["_id"]), match["teams"][side]["members"]))

@router.callback_query(F.data.startswith("captain"))
async def captain_selected(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    parts = callback.data.split(":")
    side = parts[0][-1]
    uid = int(parts[-1])
    other = "B" if side == "A" else "A"
    if match["teams"][other].get("captain_id") == uid:
        await callback.answer("One player cannot captain both teams.", show_alert=True); return
    await matches.update_one({"_id": match["_id"]}, {"$set": {f"teams.{side}.captain_id": uid}})
    await callback.answer(f"Team {side} captain selected!")
    match["teams"][side]["captain_id"] = uid
    if side == "B" and match["teams"]["A"].get("captain_id"):
        await callback.message.answer("🎲 TOSS TIME!", reply_markup=toss_kb())

@router.message(Command("toss"))
async def toss_cmd(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    await message.answer("🎲 TOSS TIME!", reply_markup=toss_kb())

@router.callback_query(F.data.startswith("toss:"))
async def toss_result(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host(callback, match):
        await callback.answer("Only Host Can Control This Game!", show_alert=True); return
    winner = random.choice(["A", "B"])
    await matches.update_one({"_id": match["_id"]}, {"$set": {"toss_winner": winner, "stage": "decision"}})
    cap = match["teams"][winner].get("captain_id")
    await callback.message.answer(f"🎉 Team {winner} won the toss! Captain: {mention(cap, 'Captain') if cap else 'Captain'} choose Bat or Bowl:", reply_markup=bat_bowl_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("decision:"))
async def bat_bowl_decision(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match:
        await callback.answer("No active match", show_alert=True); return
    winner = match.get("toss_winner")
    if callback.from_user.id != match["teams"][winner].get("captain_id") and callback.from_user.id != match.get("host_id"):
        await callback.answer("Only Winning Captain Can Choose!", show_alert=True); return
    choice = callback.data.split(":")[1]
    batting = winner if choice == "bat" else ("B" if winner == "A" else "A")
    bowling = "B" if batting == "A" else "A"
    innings = {"number": 1, "batting": batting, "bowling": bowling, "runs": 0, "wickets": 0,
        "legal_balls": 0, "extras": {"wides": 0, "no_balls": 0, "byes": 0, "leg_byes": 0},
        "batters": {}, "bowlers": {}, "fall_of_wickets": [], "partnership": 0,
        "partnership_balls": 0, "partnership_milestones": [], "hat_trick_streak": 0}
    await matches.update_one({"_id": match["_id"]}, {"$set": {"innings": [innings], "current_innings": 1, "status": "live", "stage": "live"}})
    # Pre-match scorecard and complete team rosters.
    await callback.message.answer(
        "📊 <b>LIVE SCORECARD</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏏 {match['teams']['A']['name']}: 0/0 (0.0 ov)\n"
        f"⚾ {match['teams']['B']['name']}: 0/0 (0.0 ov)\n"
        f"\n🏆 <b>TEAM {batting} vs TEAM {bowling}</b>"
    )
    roster_lines = ["👥 <b>TEAM LISTS</b>"]
    for side in ("A", "B"):
        roster_lines.append(f"\n<b>{match['teams'][side]['name']} ({len(match['teams'][side]['members'])} Members)</b>")
        for index, player in enumerate(match["teams"][side]["members"], 1):
            crown = " 👑" if match["teams"][side].get("captain_id") == player["user_id"] else ""
            roster_lines.append(f"{index}. {mention(player['user_id'], player['name'])}{crown}")
    await callback.message.answer("\n".join(roster_lines))
    await callback.message.answer(
        "🏏 <b>MATCH STARTS!</b>\n"
        f"Overs: {match['settings'].get('overs')} | Wickets: {match['settings'].get('wickets')}\n"
        f"🏏 Batting: Team {batting} | ⚾ Bowling: Team {bowling}"
    )
    await send_event_media(callback.message, "match_start")
    from bot.handlers.game import begin_opening_selection
    updated = await matches.find_one({"_id": match["_id"]})
    await begin_opening_selection(callback.message, updated, batting, bowling)
    await callback.answer()

@router.message(Command("swap_innings"))
async def swap_innings(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    if len(match.get("innings", [])) != 1 or match.get("stage") != "innings_break":
        await message.reply("First innings must be completed before /swap_innings."); return
    first = match["innings"][0]
    batting = first["bowling"]
    bowling = first["batting"]
    target = first["runs"] + 1
    second = {"number": 2, "batting": batting, "bowling": bowling, "target": target, "runs": 0, "wickets": 0,
        "legal_balls": 0, "extras": {"wides": 0, "no_balls": 0, "byes": 0, "leg_byes": 0},
        "batters": {}, "bowlers": {}, "fall_of_wickets": [], "partnership": 0,
        "partnership_balls": 0, "partnership_milestones": [], "hat_trick_streak": 0}
    await matches.update_one({"_id": match["_id"]}, {"$push": {"innings": second}, "$set": {"current_innings": 2, "stage": "live", "current": {}}})
    await send_event_media(message, "innings_2")
    lines = ["⚡ <b>INNINGS 2 STARTS!</b>", f"Team {batting} need {target} to win!", "", f"🏏 <b>Batting: Team {batting}</b>"]
    lines += [f"  • {'👑 ' if match['teams'][batting].get('captain_id') == p['user_id'] else ''}{mention(p['user_id'], p['name'])}" for p in match['teams'][batting]['members']]
    lines += ["", f"⚾ <b>Bowling: Team {bowling}</b>"]
    lines += [f"  • {'👑 ' if match['teams'][bowling].get('captain_id') == p['user_id'] else ''}{mention(p['user_id'], p['name'])}" for p in match['teams'][bowling]['members']]
    await message.answer("\n".join(lines))
    updated = await matches.find_one({"_id": match["_id"]})
    from bot.handlers.game import begin_opening_selection
    await begin_opening_selection(message, updated, batting, bowling)

@router.message(Command("change_host"))
async def change_host(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host_or_admin(message, match):
        await message.reply("❌ Only Host or Group Admin Can Change Host!"); return
    players = match["teams"]["A"]["members"] + match["teams"]["B"]["members"]
    await message.answer("👑 Choose new host:", reply_markup=player_select_kb("newhost", str(match["_id"]), players))

@router.callback_query(F.data.startswith("newhost:"))
async def newhost(callback: CallbackQuery):
    match = await active_match(callback.message.chat.id)
    if not match or not await require_host_or_admin(callback, match):
        await callback.answer("Only Host or Group Admin!", show_alert=True); return
    uid = int(callback.data.split(":")[-1])
    player = next((p for s in ("A", "B") for p in match["teams"][s]["members"] if p["user_id"] == uid), None)
    if not player:
        await callback.answer("Player not found", show_alert=True); return
    await matches.update_one({"_id": match["_id"]}, {"$set": {"host_id": uid, "host_name": player["name"]}})
    await callback.message.answer(f"👑 New Host: {mention(uid, player['name'])}")
    await callback.answer()

@router.message(Command("endgame"))
async def endgame(message: Message):
    match = await active_match(message.chat.id)
    if not match:
        await message.reply("No active match."); return
    if not await require_host_or_admin(message, match):
        await message.reply("❌ Only Host or Group Admin Can End This Match!"); return
    await matches.update_one({"_id": match["_id"]}, {"$set": {"status": "ended", "stage": "ended", "ended_at": datetime.now(timezone.utc), "ended_by": message.from_user.id}})
    await message.answer("🏁 <b>MATCH ENDED BY HOST / ADMIN!</b>\nMatch history and statistics have been preserved.")

# Host-only roster management. /add_a and /add_b are used by replying to a player's message.
@router.message(Command("add_a", "add_b"))
async def add_player_command(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Reply to the player's message with /add_a or /add_b."); return
    side = "A" if message.text.split()[0].endswith("add_a") else "B"
    user = message.reply_to_message.from_user
    if any(p["user_id"] == user.id for s in ("A", "B") for p in match["teams"][s]["members"]):
        await message.reply("That player is already in a team."); return
    match["teams"][side]["members"].append({"user_id": user.id, "name": user.full_name, "is_ai": False})
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer(await roster_text(match), reply_markup=join_kb())

@router.message(Command("remove_player"))
async def remove_player_command(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Reply to the player's message with /remove_player."); return
    uid = message.reply_to_message.from_user.id
    removed = False
    for side in ("A", "B"):
        before = len(match["teams"][side]["members"])
        match["teams"][side]["members"] = [p for p in match["teams"][side]["members"] if p["user_id"] != uid]
        removed = removed or before != len(match["teams"][side]["members"])
        if match["teams"][side].get("captain_id") == uid:
            match["teams"][side]["captain_id"] = None
    if not removed:
        await message.reply("Player not found in either team."); return
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer(await roster_text(match), reply_markup=join_kb())

@router.message(Command("swap"))
async def swap_players_command(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    if not message.reply_to_message or not message.reply_to_message.from_user or not message.text.split()[1:]:
        await message.reply("Reply to the first player and use /swap SECOND_PLAYER_ID."); return
    first_id = message.reply_to_message.from_user.id
    try:
        second_id = int(message.text.split()[1])
    except ValueError:
        await message.reply("Use the second player's numeric Telegram ID."); return
    first_side = next((s for s in ("A", "B") if any(p["user_id"] == first_id for p in match["teams"][s]["members"])), None)
    second_side = next((s for s in ("A", "B") if any(p["user_id"] == second_id for p in match["teams"][s]["members"])), None)
    if not first_side or not second_side or first_side == second_side:
        await message.reply("Both players must be in opposite teams."); return
    p1 = next(p for p in match["teams"][first_side]["members"] if p["user_id"] == first_id)
    p2 = next(p for p in match["teams"][second_side]["members"] if p["user_id"] == second_id)
    match["teams"][first_side]["members"].remove(p1); match["teams"][second_side]["members"].remove(p2)
    match["teams"][first_side]["members"].append(p2); match["teams"][second_side]["members"].append(p1)
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer("🔄 Players swapped successfully!\n" + await roster_text(match))

@router.message(Command("add_ai_a", "add_ai_b"))
async def add_ai_command(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    side = "A" if message.text.split()[0].endswith("add_ai_a") else "B"
    ai_count = sum(1 for p in match["teams"][side]["members"] if p.get("is_ai")) + 1
    ai_id = -random.randint(100000, 999999999)
    match["teams"][side]["members"].append({"user_id": ai_id, "name": f"AI Player {ai_count}", "is_ai": True})
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer(await roster_text(match))

@router.message(Command("remove_ai"))
async def remove_ai_command(message: Message):
    match = await active_match(message.chat.id)
    if not match or not await require_host(message, match):
        await message.reply("❌ Only Host Can Control This Game!"); return
    removed = 0
    for side in ("A", "B"):
        before = len(match["teams"][side]["members"])
        match["teams"][side]["members"] = [p for p in match["teams"][side]["members"] if not p.get("is_ai")]
        removed += before - len(match["teams"][side]["members"])
    await matches.update_one({"_id": match["_id"]}, {"$set": {"teams": match["teams"]}})
    await message.answer(f"🤖 Removed {removed} AI player(s).\n" + await roster_text(match))
