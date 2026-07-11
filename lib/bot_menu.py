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
        [
            {"text": "📊 فرم اخیر تیم‌ها", "callback_data": "form"},
            {"text": "⚔️ تاریخچه رو در رو", "callback_data": "h2h"},
        ],
        [
            {"text": "👑 برترین‌های جام جهانی", "callback_data": "leaders"},
            {"text": "💬 سوال از هوش مصنوعی", "callback_data": "chat"},
        ],
        [
            {"text": "📋 جدول گروه‌ها", "callback_data": "standings"},
            {"text": "🏆 نمودار حذفی", "callback_data": "bracket"},
        ],
        [
            {"text": "👟 برترین گلزن‌ها", "callback_data": "scorers"},
            {"text": "🎯 برترین پاسورها", "callback_data": "assists"},
        ],
        [
            {"text": "📄 ترکیب بازی بعدی", "callback_data": "lineups"},
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
    "زمان و تحلیل بازی بعدی رو ببینی. همچنین:\n\n"
    "📊 فرم اخیر تیم‌ها | ⚔️ تاریخچه رو در رو\n"
    "👑 برترین‌های جام جهانی | 💬 سوال از هوش مصنوعی\n"
    "📋 جدول گروه‌ها | 🏆 نمودار حذفی\n"
    "👟 برترین گلزن‌ها | 🎯 برترین پاسورها\n"
    "📄 ترکیب بازی بعدی"
)

# Prompt shown when user taps the chat button
CHAT_PROMPT = (
    "💬 هر سوالی درباره‌ی فوتبال یا جام جهانی داری رو بنویس!\n\n"
    "مثلاً:\n"
    "• «وضعیت بازی نروژ چیه؟»\n"
    "• «آخرین گل کی زد؟»\n"
    "• «قانون آفساید چیه؟»\n"
    "• «تاریخچه‌ی بازی‌های ایران و آمریکا چطور بوده؟»\n\n"
    "سوالت رو بفرست تا جواب بگیرم 🤖"
)
