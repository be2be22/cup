"""Inline keyboard definitions for the interactive Telegram bot menu."""

MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "🔴 وضعیت بازی زنده", "callback_data": "live"}],
        [
            {"text": "📋 نتیجه بازی قبلی", "callback_data": "last"},
            {"text": "⏭ بازی بعدی + تحلیل", "callback_data": "next"},
        ],
        [
            {"text": "📅 برنامه امروز", "callback_data": "today"},
            {"text": "ℹ️ راهنما", "callback_data": "help"},
        ],
    ]
}

# Shown under every reply so the user can jump to another option
# without retyping /start.
BACK_TO_MENU = {
    "inline_keyboard": [[{"text": "⬅️ بازگشت به منو", "callback_data": "menu"}]]
}

WELCOME_TEXT = (
    "👋 سلام! به ربات جام جهانی ۲۰۲۶ خوش اومدی.\n\n"
    "از دکمه‌های زیر می‌تونی وضعیت بازی زنده، نتیجه‌ی آخرین بازی، یا "
    "زمان و تحلیل بازی بعدی رو ببینی."
)
