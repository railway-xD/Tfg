from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ 1v1 Rivalry", callback_data="mode:1v1")],
        [InlineKeyboardButton(text="🤖 Play vs Assistant", callback_data="mode:assistant")],
        [InlineKeyboardButton(text="🏆 Solo Mode", callback_data="mode:solo")],
        [InlineKeyboardButton(text="👥 Team Match", callback_data="mode:team")],
        [InlineKeyboardButton(text="🏟️ Enter the Arena", callback_data="mode:arena")],
        [InlineKeyboardButton(text="📢 Follow Updates", url="https://t.me/")],
    ])


def host_claim_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 I'm the Host!", callback_data="claim_host")]
    ])


def join_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔵 Join Team A", callback_data="join:A"),
         InlineKeyboardButton(text="🔴 Join Team B", callback_data="join:B")]
    ])


def overs_kb():
    rows, row = [], []
    for n in range(1, 51):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"overs:{n}"))
        if len(row) == 5:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wickets_kb():
    rows, row = [], []
    for n in range(1, 26):
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"wickets:{n}"))
        if len(row) == 5:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🤖 Auto (All Out)", callback_data="wickets:auto")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yes_no_kb(prefix: str, yes: str, no: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes, callback_data=f"{prefix}:on"),
        InlineKeyboardButton(text=no, callback_data=f"{prefix}:off"),
    ]])


def weather_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="☀️ Normal", callback_data="weather:normal"),
        InlineKeyboardButton(text="🌧️ Rainy", callback_data="weather:rainy"),
    ]])


def player_select_kb(prefix: str, match_id: str, players: list[dict], exclude=None):
    exclude = set(exclude or [])
    rows = []
    for p in players:
        if p.get("user_id") in exclude:
            continue
        rows.append([InlineKeyboardButton(
            text=("🤖 " if p.get("is_ai") else "") + p.get("name", "Player")[:45],
            callback_data=f"{prefix}:{match_id}:{p['user_id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(prefix: str, match_id: str, user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm", callback_data=f"confirm:{prefix}:{match_id}:{user_id}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel:{prefix}:{match_id}"),
    ]])


def toss_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🪙 Heads", callback_data="toss:heads"),
        InlineKeyboardButton(text="🪙 Tails", callback_data="toss:tails"),
    ], [InlineKeyboardButton(text="🎲 Roll Dice Instead", callback_data="toss:dice")]])


def bat_bowl_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏏 Bat", callback_data="decision:bat"),
        InlineKeyboardButton(text="⚾ Bowl", callback_data="decision:bowl"),
    ]])
