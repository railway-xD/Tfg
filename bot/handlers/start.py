from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.filters.command import CommandObject
from bot.keyboards import main_menu_kb
from bot.services.formatting import help_text

router = Router()

@router.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    args = command.args or ""
    if args.startswith("bowl_"):
        from bot.handlers.game import bowl_deep_link
        await bowl_deep_link(message, command)
        return
    await message.answer(
        "🏏 <b>WELCOME TO TFG CRICKET RIVALRY!</b>\n\n"
        "🔥 Your Ultimate Telegram Hand Cricket Experience!\n\n"
        "⚔️ Create Teams\n🏆 Play Matches\n🎯 Live Score Updates\n"
        "🎥 Cricket Videos & Celebrations\n\n"
        "Use /help to view all bot commands.",
        reply_markup=main_menu_kb(),
    )

@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(help_text())
