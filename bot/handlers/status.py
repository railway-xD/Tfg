from html import escape
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bot.db import matches
from bot.services.statistics import overs_text, strike_rate, economy, run_rate, extras_total

router = Router()

@router.message(Command("status"))
async def status_cmd(message: Message):
    match = await matches.find_one({"chat_id": message.chat.id, "status": {"$in": ["setup", "live"]}}, sort=[("created_at", -1)])
    if not match:
        await message.answer("📊 No active match in this group."); return
    if match.get("status") != "live" or not match.get("innings"):
        await message.answer(f"📊 <b>TFG CRICKET RIVALRY — STATUS</b>\nStage: {match.get('stage','setup')}\nHost: {match.get('host_name','—')}\nTeam A: {len(match['teams']['A']['members'])} members\nTeam B: {len(match['teams']['B']['members'])} members")
        return
    inn = match["innings"][match.get("current_innings", 1)-1]
    a, b = match["teams"]["A"], match["teams"]["B"]
    lines = ["📊 <b>SCOREBOARD</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for side, team in (("A", a), ("B", b)):
        total = sum(i["runs"] for i in match["innings"] if i["batting"] == side)
        wickets = sum(i["wickets"] for i in match["innings"] if i["batting"] == side)
        last = next((i for i in reversed(match["innings"]) if i["batting"] == side), None)
        ov = overs_text(last["legal_balls"]) if last else "0.0"
        ext = sum(last.get("extras", {}).values()) if last else 0
        rr = run_rate(last.get("runs", 0), last.get("legal_balls", 0)) if last else 0.0
        lines.append(f"🏏 {team['name']}: {total}/{wickets} ({ov} ov) | Ext: {ext} | RR: {rr:.2f}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for uid, stats in inn.get("batters", {}).items():
        marker = " *" if int(uid) == match.get("current", {}).get("striker_id") else ""
        sr = strike_rate(stats.get("runs", 0), stats.get("balls", 0))
        status = " OUT" if stats.get("out") else ""
        lines.append(f"🏏 {escape(stats.get('name','Batter'))}: {stats.get('runs',0)}({stats.get('balls',0)}b) | 4s:{stats.get('fours',0)} 6s:{stats.get('sixes',0)} | SR:{sr:.2f}{status}{marker}")
    for uid, stats in inn.get("bowlers", {}).items():
        legal = stats.get("legal_balls", 0)
        econ = economy(stats.get("runs", 0), legal)
        lines.append(f"⚾ {escape(stats.get('name','Bowler'))}: {overs_text(legal)} ov | {stats.get('wickets',0)}wkt | {stats.get('runs',0)} runs | Econ {econ:.2f}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    rr = run_rate(inn.get("runs", 0), inn.get("legal_balls", 0))
    lines.append(f"📋 Inn{inn['number']} | {overs_text(inn['legal_balls'])}/{match['settings'].get('overs', '?')} ov | CRR: {rr:.2f}")
    extras = inn.get("extras", {})
    lines.append("➕ Extras: " + ", ".join(f"{k.replace('_',' ').title()} {v}" for k, v in extras.items()) + f" | Total {extras_total(extras)}")
    fow = inn.get("fall_of_wickets", [])
    if fow:
        lines.append("💥 Fall of wickets: " + ", ".join(f"{w.get('score')}/{w.get('wicket')} ({w.get('over')})" for w in fow))
    if inn.get("target"):
        need = max(0, inn['target']-inn['runs'])
        balls_left = max(0, int(match['settings'].get('overs', 0))*6-inn['legal_balls'])
        rrr = need*6/balls_left if balls_left else 0
        lines.append(f"🎯 Target: {inn['target']} | Need: {need} runs | Balls left: {balls_left} | RRR: {rrr:.2f}")
    await message.answer("\n".join(lines))
