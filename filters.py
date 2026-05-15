import re

SIGNAL_WORDS = {
    "long", "short", "buy", "sell", "entry", "tp", "target",
    "sl", "stoploss", "stop loss", "takeprofit", "take profit",
    "position", "trade", "signal", "leverage", "breakout",
    # Russian
    "лонг", "шорт", "покупка", "продажа", "вход", "цель", "стоп",
    "сигнал", "позиция", "трейд",
}

SPAM_WORDS = {
    "airdrop", "giveaway", "claim", "bonus", "casino", "presale",
    "pre-sale", "ido", "ico", "free", "win", "winner", "lucky",
    "prize", "referral", "реферал", "раздача", "бесплатно",
    "выиграй", "дроп", "скам", "scam", "pump", "promo",
}

_RE_WORD = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_RE_SPACES = re.compile(r"\s+")


def _tokens(text: str) -> set[str]:
    return {m.lower() for m in _RE_WORD.findall(text)}


def is_spam(text: str) -> bool:
    tokens = _tokens(text)
    if tokens & SPAM_WORDS:
        return True
    lower = text.lower()
    for phrase in SPAM_WORDS:
        if " " in phrase and phrase in lower:
            return True
    return False


def has_signal(text: str) -> bool:
    tokens = _tokens(text)
    lower = text.lower()
    for word in SIGNAL_WORDS:
        if " " in word:
            if word in lower:
                return True
        elif word in tokens:
            return True
    return False


def should_pass(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "empty"
    if is_spam(text):
        return False, "spam"
    if not has_signal(text):
        return False, "no_signal"
    return True, "ok"
