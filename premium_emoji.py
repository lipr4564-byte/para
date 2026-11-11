"""
Premium-эмодзи для сообщений и кнопок
"""

from aiogram.types import InlineKeyboardButton


def ce(emoji_id: str, fallback: str = "⬜") -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


EMOJI_MAP = {
    "📋": "5292022831117266575",
    "👑": "5291837438853932986",
    "🏳️": "5291853424722208476",
    "🛡️": "5289736924968283535",
    "⚔️": "5292251447931461936",
    "💣": "5291750019089590953",
    "🌐": "5292032872750803545",
    "🔙": "5292014236887704329",
    "✅": "5350392424512375184",
    "❌": "5893163582194978381",
    "📅": "5291920885773526040",
    "📢": "5291794407576594973",
    "🗑️": "5289839299808750163",
    "🔄": "5292153922109072253",
    "📊": "5292107175685023970",
    "🤝": "5291926718339114379",
    "🚪": "5291932460710391663",
    "✏️": "5292151980783855011",
    "⛔": "5393198774413703582",
    "🤖": "5291879924670425618",
    "🔗": "5291984352505259255",
    "📍": "5292139001392688070",
    "😔": "5291750019089590953",
    "❓": "5292034556377985740",
    "⚠️": "5291808525134095675",
    "📩": "5291793896475486807",
    "🎯": "5292107175685023970",
    "🔧": "5292284450460164330",
    "👥": "5291926718339114379",
    "💎": "5291753201660355374",
    "🌍": "5292032872750803545",
    "🏠": "5289876283772135018",
}


def pe(emoji: str) -> str:
    """Premium-эмодзи для HTML-текста"""
    emoji_id = EMOJI_MAP.get(emoji)
    if emoji_id:
        return ce(emoji_id, emoji)
    return emoji


def btn(text: str, callback_data: str, emoji: str = None) -> InlineKeyboardButton:
    """Кнопка с premium-эмодзи через icon_custom_emoji_id"""
    kwargs = {"text": text, "callback_data": callback_data}
    emoji_id = EMOJI_MAP.get(emoji) if emoji else None
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(**kwargs)