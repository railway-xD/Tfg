"""User-editable media slots. Use Telegram file_id strings or local paths in media/."""
from pathlib import Path
from aiogram.types import FSInputFile

MEDIA = {
    # 🖼️ NEW MATCH / WELCOME BANNER PHOTO
    "welcome_banner": None,
    # 🎬 MATCH START VIDEO
    "match_start": None,
    # 🎬 INNINGS BREAK VIDEO (after Innings 1 ends)
    "innings_break": None,
    # 🎬 INNINGS 2 START VIDEO (when Host uses /swap_innings)
    "innings_2": None,
    # 🎬 0 RUN / DOT BALL GIF
    "dot": None,
    # 🎬 1 RUN GIF
    "run_1": None,
    # 🎬 2 RUNS GIF
    "run_2": None,
    # 🎬 3 RUNS GIF
    "run_3": None,
    # 🎬 FOUR GIF
    "four": None,
    # 🎬 5 RUNS GIF
    "run_5": None,
    # 🎬 SIX GIF
    "six": None,
    # 🎬 WICKET GIF
    "wicket": None,
    # 🎬 NO-BALL GIF
    "no_ball": None,
    # 🎬 HALF-CENTURY GIF
    "fifty": None,
    # 🎬 CENTURY GIF
    "hundred": None,
    # 🎬 150 RUNS GIF
    "one_fifty": None,
    # 🎬 DOUBLE-CENTURY GIF
    "two_hundred": None,
    # 🎬 50-RUN PARTNERSHIP GIF
    "partnership_50": None,
    # 🎬 100-RUN PARTNERSHIP GIF
    "partnership_100": None,
    # 🎬 150-RUN PARTNERSHIP GIF
    "partnership_150": None,
    # 🎬 HAT-TRICK GIF
    "hat_trick": None,
    # 🎬 MATCH RESULT / WINNER GIF
    "match_result": None,
}

# For Telegram file_id values, set the media kind here.
# Allowed kinds: "video", "animation", "photo".
MEDIA_KIND = {
    "welcome_banner": "photo",
    "dot": "animation",
    "run_1": "animation",
    "run_2": "animation",
    "run_3": "animation",
    "four": "animation",
    "run_5": "animation",
    "six": "animation",
    "wicket": "animation",
    "no_ball": "animation",
    "fifty": "animation",
    "hundred": "animation",
    "one_fifty": "animation",
    "two_hundred": "animation",
    "partnership_50": "animation",
    "partnership_100": "animation",
    "partnership_150": "animation",
    "hat_trick": "animation",
    "innings_2": "video",
}

async def send_event_media(message, key: str, caption: str | None = None):
    value = MEDIA.get(key)
    if not value:
        return False
    try:
        path = Path(value) if isinstance(value, str) else None
        file = FSInputFile(path) if path and path.is_file() else value
        kind = MEDIA_KIND.get(key, "video")
        if path and path.suffix.lower() in (".gif", ".webp"):
            kind = "animation"
        elif path and path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            kind = "photo"
        if kind == "animation":
            await message.answer_animation(file, caption=caption)
        elif kind == "photo":
            await message.answer_photo(file, caption=caption)
        else:
            await message.answer_video(file, caption=caption)
        return True
    except Exception as exc:
        print(f"Media slot '{key}' failed: {exc}")
        return False
