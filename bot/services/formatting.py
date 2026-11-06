from html import escape

COMMANDS = [
    ("/start", "Welcome message", "Everyone"),
    ("/help", "Show all commands", "Everyone"),
    ("/newmatch", "Create a new match", "Everyone"),
    ("/join_a", "Join Team A", "Everyone"),
    ("/join_b", "Join Team B", "Everyone"),
    ("/add_a", "Add a player to Team A", "Host"),
    ("/add_b", "Add a player to Team B", "Host"),
    ("/swap", "Swap players between teams", "Host"),
    ("/remove_player", "Remove a player", "Host"),
    ("/add_ai_a", "Add AI player to Team A", "Host"),
    ("/add_ai_b", "Add AI player to Team B", "Host"),
    ("/remove_ai", "Remove an AI player", "Host"),
    ("/extend", "Extend joining time", "Host"),
    ("/startmatch", "Start match setup", "Host"),
    ("/choose_captain", "Choose team captains", "Host"),
    ("/toss", "Start toss", "Host"),
    ("/swap_innings", "Start second innings", "Host"),
    ("/change_host", "Change match host", "Host / Group Admin"),
    ("/status", "Show live scoreboard", "Everyone"),
    ("/endgame", "End current match", "Host / Group Admin"),
]


def help_text():
    lines = ["🏏 <b>TFG CRICKET RIVALRY — COMMANDS</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for command, desc, permission in COMMANDS:
        lines.append(f"<code>{command}</code> — {escape(desc)} <i>({escape(permission)})</i>")
    lines += ["━━━━━━━━━━━━━━━━━━━━", "🎮 Host controls match setup and game flow.", "👥 Anyone can join teams and check /status."]
    return "\n".join(lines)


def mention(user_id: int, name: str) -> str:
    if int(user_id) < 0:
        return "🤖 " + escape(name)
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'
