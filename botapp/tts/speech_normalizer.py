from __future__ import annotations

from dataclasses import dataclass
import re


_MONTHS_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

_UNICODE_REPLACEMENTS = {
    "\u00a0": " ",
    "\u2007": " ",
    "\u202f": " ",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": " — ",
    "\u2212": "-",
    "\u2044": "/",
    "\u2215": "/",
    "\u00d7": " x ",
}

_CURRENCY_FORMS = {
    "$": ("доллар", "доллара", "долларов"),
    "€": ("евро", "евро", "евро"),
    "₽": ("рубль", "рубля", "рублей"),
}

_SCALE_FORMS = {
    "тыс": ("тысяча", "тысячи", "тысяч"),
    "млн": ("миллион", "миллиона", "миллионов"),
    "млрд": ("миллиард", "миллиарда", "миллиардов"),
}

_UNIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(-?\d+(?:[.,]\d+)?)\s*км\s*/\s*ч\b", re.IGNORECASE),
        "километр в час",
    ),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*м\s*/\s*с\b", re.IGNORECASE), "метр в секунду"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*кВт\s*ч\b", re.IGNORECASE), "киловатт-час"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*км\b", re.IGNORECASE), "километр"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*мг\b", re.IGNORECASE), "миллиграмм"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*кг\b", re.IGNORECASE), "килограмм"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*г\b", re.IGNORECASE), "грамм"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*см\b", re.IGNORECASE), "сантиметр"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*мм\b", re.IGNORECASE), "миллиметр"),
    (re.compile(r"(-?\d+(?:[.,]\d+)?)\s*м\b", re.IGNORECASE), "метр"),
)

_KNOWN_LATIN_PHRASES = {
    "openai": "оупен эй ай",
    "nvidia": "энвидиа",
    "wifi": "вай фай",
    "wi-fi": "вай фай",
    "usb-c": "ю эс би си",
    "gpt": "джи пи ти",
    "rtx": "эр ти икс",
}

_ABBREVIATION_NAMES = {
    "A": "эй",
    "B": "би",
    "C": "си",
    "D": "ди",
    "E": "и",
    "F": "эфф",
    "G": "джи",
    "H": "эйч",
    "I": "ай",
    "J": "джей",
    "K": "кей",
    "L": "эль",
    "M": "эм",
    "N": "эн",
    "O": "оу",
    "P": "пи",
    "Q": "кью",
    "R": "ар",
    "S": "эс",
    "T": "ти",
    "U": "ю",
    "V": "ви",
    "W": "дабл ю",
    "X": "икс",
    "Y": "уай",
    "Z": "зет",
}

_LATIN_DIGRAPHS = (
    ("sch", "щ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("ya", "я"),
    ("yu", "ю"),
    ("yo", "ё"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ts", "ц"),
    ("ph", "ф"),
    ("th", "т"),
    ("qu", "кв"),
    ("ck", "к"),
)

_GENITIVE_NUMERAL_WORDS = {
    "один": "одного",
    "одна": "одной",
    "два": "двух",
    "две": "двух",
    "три": "трех",
    "четыре": "четырех",
    "пять": "пяти",
    "шесть": "шести",
    "семь": "семи",
    "восемь": "восьми",
    "девять": "девяти",
    "десять": "десяти",
    "одиннадцать": "одиннадцати",
    "двенадцать": "двенадцати",
    "тринадцать": "тринадцати",
    "четырнадцать": "четырнадцати",
    "пятнадцать": "пятнадцати",
    "шестнадцать": "шестнадцати",
    "семнадцать": "семнадцати",
    "восемнадцать": "восемнадцати",
    "девятнадцать": "девятнадцати",
    "двадцать": "двадцати",
    "тридцать": "тридцати",
    "сорок": "сорока",
    "пятьдесят": "пятидесяти",
    "шестьдесят": "шестидесяти",
    "семьдесят": "семидесяти",
    "восемьдесят": "восьмидесяти",
    "девяносто": "девяноста",
    "сто": "ста",
    "двести": "двухсот",
    "триста": "трехсот",
    "четыреста": "четырехсот",
    "пятьсот": "пятисот",
    "шестьсот": "шестисот",
    "семьсот": "семисот",
    "восемьсот": "восьмисот",
    "девятьсот": "девятисот",
    "тысяча": "тысячи",
    "тысячи": "тысяч",
    "миллион": "миллиона",
    "миллиона": "миллионов",
    "миллиард": "миллиарда",
    "миллиарда": "миллиардов",
}

_LATIN_LETTERS = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "дж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "й",
    "z": "з",
}

_TOKEN_RE = re.compile(r"\b[\w./+-]*[A-Za-z][\w./+-]*\b")
_NUMBER_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])(-?\d+(?:[.,]\d+)?)(?![A-Za-zА-Яа-яЁё])")
_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_DATE_YMD_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MONEY_RE = re.compile(
    r"([$€₽])\s*(\d+(?:[.,]\d+)?)\s*(млрд|млн|тыс)?\b", re.IGNORECASE
)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_TEMPERATURE_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*°\s*([CF])\b", re.IGNORECASE)
_FRACTION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
_RANGE_RE = re.compile(r"\b(-?\d+(?:[.,]\d+)?)\s*[–-]\s*(-?\d+(?:[.,]\d+)?)\b")


@dataclass(frozen=True)
class SpeechNormalizationResult:
    text: str
    changed: bool


def normalize_for_speech(text: str) -> str:
    return speech_normalize(text).text


def speech_normalize(text: str) -> SpeechNormalizationResult:
    normalized = text or ""
    for source, target in _UNICODE_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\s+([.,;:!?])", r"\1", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)

    normalized = _MONEY_RE.sub(_replace_money, normalized)
    normalized = _TEMPERATURE_RE.sub(_replace_temperature, normalized)
    normalized = _PERCENT_RE.sub(_replace_percent, normalized)
    normalized = _replace_units(normalized)
    normalized = _FRACTION_RE.sub(_replace_fraction, normalized)
    normalized = _DATE_DMY_RE.sub(_replace_dmy_date, normalized)
    normalized = _DATE_YMD_RE.sub(_replace_ymd_date, normalized)
    normalized = _RANGE_RE.sub(_replace_range, normalized)
    normalized = _TOKEN_RE.sub(_replace_latin_token, normalized)
    normalized = _NUMBER_RE.sub(_replace_plain_number, normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    normalized = re.sub(r" ?\n ?", "\n", normalized)
    return SpeechNormalizationResult(
        text=normalized.strip(), changed=normalized.strip() != (text or "").strip()
    )


def _replace_money(match: re.Match[str]) -> str:
    symbol, amount, scale = match.groups()
    amount_words = _number_to_words(amount)
    parts = [amount_words]
    if scale:
        parts.append(_select_form(_parse_number(amount), _SCALE_FORMS[scale.lower()]))
    parts.append(_select_form(_parse_number(amount), _CURRENCY_FORMS[symbol]))
    return " ".join(parts)


def _replace_temperature(match: re.Match[str]) -> str:
    value, scale = match.groups()
    unit = "градус Цельсия" if scale.upper() == "C" else "градус Фаренгейта"
    return f"{_number_to_words(value)} {_select_form(_parse_number(value), _unit_forms(unit))}"


def _replace_percent(match: re.Match[str]) -> str:
    value = match.group(1)
    return f"{_number_to_words(value)} {_select_form(_parse_number(value), ('процент', 'процента', 'процентов'))}"


def _replace_fraction(match: re.Match[str]) -> str:
    numerator = int(match.group(1))
    denominator = int(match.group(2))
    common = {
        2: ("вторая", "вторых"),
        3: ("треть", "третьих"),
        4: ("четверть", "четвертых"),
        5: ("пятая", "пятых"),
        6: ("шестая", "шестых"),
        8: ("восьмая", "восьмых"),
        10: ("десятая", "десятых"),
    }
    if denominator in common:
        if numerator == 1:
            return f"одна {common[denominator][0]}"
        return f"{_integer_to_words(numerator, feminine=True)} {common[denominator][1]}"
    return f"{_integer_to_words(numerator)} дробь {_integer_to_words(denominator)}"


def _replace_dmy_date(match: re.Match[str]) -> str:
    day, month, year = (int(part) for part in match.groups())
    if month not in _MONTHS_GENITIVE:
        return match.group(0)
    return f"{_integer_to_words(day)} {_MONTHS_GENITIVE[month]} {_integer_to_words(year)} года"


def _replace_ymd_date(match: re.Match[str]) -> str:
    year, month, day = (int(part) for part in match.groups())
    if month not in _MONTHS_GENITIVE:
        return match.group(0)
    return f"{_integer_to_words(day)} {_MONTHS_GENITIVE[month]} {_integer_to_words(year)} года"


def _replace_range(match: re.Match[str]) -> str:
    start, end = match.groups()
    return f"от {_to_genitive(_number_to_words(start))} до {_to_genitive(_number_to_words(end))}"


def _replace_latin_token(match: re.Match[str]) -> str:
    token = match.group(0)
    replacement = _normalize_latin_token(token)
    return replacement if replacement else token


def _replace_plain_number(match: re.Match[str]) -> str:
    return _number_to_words(match.group(1))


def _replace_units(text: str) -> str:
    updated = text
    for pattern, base_unit in _UNIT_PATTERNS:
        updated = pattern.sub(
            lambda match: _format_value_with_unit(match.group(1), base_unit), updated
        )
    return updated


def _format_value_with_unit(value: str, base_unit: str) -> str:
    forms = _unit_forms(base_unit)
    return f"{_number_to_words(value)} {_select_form(_parse_number(value), forms)}"


def _unit_forms(base_unit: str) -> tuple[str, str, str]:
    irregular = {
        "километр в час": ("километр в час", "километра в час", "километров в час"),
        "метр в секунду": ("метр в секунду", "метра в секунду", "метров в секунду"),
        "киловатт-час": ("киловатт-час", "киловатт-часа", "киловатт-часов"),
        "градус Цельсия": ("градус Цельсия", "градуса Цельсия", "градусов Цельсия"),
        "градус Фаренгейта": (
            "градус Фаренгейта",
            "градуса Фаренгейта",
            "градусов Фаренгейта",
        ),
    }
    if base_unit in irregular:
        return irregular[base_unit]
    if base_unit.endswith("метр"):
        root = base_unit[:-4]
        return (base_unit, f"{root}метра", f"{root}метров")
    if base_unit.endswith("грамм"):
        root = base_unit[:-5]
        return (base_unit, f"{root}грамма", f"{root}граммов")
    if base_unit.endswith("ватт"):
        root = base_unit[:-4]
        return (base_unit, f"{root}ватта", f"{root}ватт")
    return (base_unit, f"{base_unit}а", f"{base_unit}ов")


def _normalize_latin_token(token: str) -> str:
    lowered = token.lower()
    if lowered in _KNOWN_LATIN_PHRASES:
        return _KNOWN_LATIN_PHRASES[lowered]
    if "/" in token:
        parts = [part for part in token.split("/") if part]
        normalized_parts = [_normalize_latin_token(part) for part in parts]
        return " и ".join(part for part in normalized_parts if part)
    if token.upper() == token and re.fullmatch(r"[A-Z]{1,}", token):
        return " ".join(_ABBREVIATION_NAMES.get(ch, ch.lower()) for ch in token)
    if re.fullmatch(r"\d+[A-Za-z]", token):
        return f"{_number_to_words(token[:-1])} {_normalize_latin_token(token[-1])}"
    if re.fullmatch(r"[A-Za-z]\d+(?:[.,]\d+)?", token):
        return f"{_normalize_latin_token(token[0])} {_number_to_words(token[1:])}"
    if re.fullmatch(r"[A-Za-z]+-\d+(?:[.,]\d+)?", token):
        word, number = token.rsplit("-", 1)
        return f"{_normalize_latin_token(word)} {_number_to_words(number)}"
    if "-" in token:
        parts = [part for part in token.split("-") if part]
        return " ".join(_normalize_latin_token(part) for part in parts)
    if re.fullmatch(r"[A-Za-z]+\d+(?:[.,]\d+)?", token):
        split_index = next(index for index, char in enumerate(token) if char.isdigit())
        return (
            f"{_normalize_latin_token(token[:split_index])} "
            f"{_number_to_words(token[split_index:])}"
        )
    if re.fullmatch(r"[A-Za-z][A-Za-z.]*(?:\.[A-Za-z0-9]+)+", token):
        parts = [part for part in token.split(".") if part]
        return " точка ".join(_normalize_latin_token(part) for part in parts)
    if re.search(r"[A-Z]", token) and re.search(r"[a-z]", token):
        known = _KNOWN_LATIN_PHRASES.get(lowered.replace("-", ""))
        if known:
            return known
    return _transliterate_latin_word(token)


def _transliterate_latin_word(token: str) -> str:
    stripped = token.strip(".,;:!?\"'()[]{}")
    suffix = token[len(stripped) :] if stripped and token.endswith(stripped) else ""
    prefix_len = token.find(stripped) if stripped else 0
    prefix = token[:prefix_len] if prefix_len > 0 else ""
    if not stripped:
        return token
    lowered = stripped.lower()
    if lowered in _KNOWN_LATIN_PHRASES:
        return f"{prefix}{_KNOWN_LATIN_PHRASES[lowered]}{suffix}"

    result: list[str] = []
    cursor = 0
    while cursor < len(lowered):
        for source, target in _LATIN_DIGRAPHS:
            if lowered.startswith(source, cursor):
                result.append(target)
                cursor += len(source)
                break
        else:
            char = lowered[cursor]
            result.append(_LATIN_LETTERS.get(char, char))
            cursor += 1
    return f"{prefix}{''.join(result)}{suffix}"


def _to_genitive(words: str) -> str:
    return " ".join(_GENITIVE_NUMERAL_WORDS.get(word, word) for word in words.split())


def _parse_number(value: str) -> float:
    return float(value.replace(" ", "").replace(",", "."))


def _number_to_words(value: str) -> str:
    numeric = _parse_number(value)
    if numeric.is_integer():
        return _integer_to_words(int(numeric))

    integer_part, fractional_part = _split_decimal_string(value)
    denominator_forms = {
        1: ("десятая", "десятых"),
        2: ("сотая", "сотых"),
        3: ("тысячная", "тысячных"),
    }
    denom = denominator_forms.get(len(fractional_part))
    fractional_number = int(fractional_part)
    if denom is None:
        return f"{_integer_to_words(int(integer_part))} запятая {_integer_to_words(fractional_number)}"
    fractional_words = _integer_to_words(fractional_number, feminine=True)
    suffix = denom[0] if fractional_number == 1 else denom[1]
    return (
        f"{_integer_to_words(int(integer_part), feminine=False)} целых "
        f"{fractional_words} {suffix}"
    )


def _split_decimal_string(value: str) -> tuple[str, str]:
    cleaned = value.replace(" ", "").replace(",", ".")
    integer_part, fractional_part = cleaned.split(".", 1)
    return integer_part or "0", fractional_part.rstrip("0") or "0"


def _select_form(value: float, forms: tuple[str, str, str]) -> str:
    if not float(value).is_integer():
        return forms[1]
    number = abs(int(value)) % 100
    if 11 <= number <= 14:
        return forms[2]
    number %= 10
    if number == 1:
        return forms[0]
    if 2 <= number <= 4:
        return forms[1]
    return forms[2]


def _integer_to_words(value: int, feminine: bool = False) -> str:
    if value == 0:
        return "ноль"
    if value < 0:
        return f"минус {_integer_to_words(abs(value), feminine=feminine)}"

    ones_m = [
        "",
        "один",
        "два",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    ]
    ones_f = [
        "",
        "одна",
        "две",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    ]
    teens = [
        "десять",
        "одиннадцать",
        "двенадцать",
        "тринадцать",
        "четырнадцать",
        "пятнадцать",
        "шестнадцать",
        "семнадцать",
        "восемнадцать",
        "девятнадцать",
    ]
    tens = [
        "",
        "",
        "двадцать",
        "тридцать",
        "сорок",
        "пятьдесят",
        "шестьдесят",
        "семьдесят",
        "восемьдесят",
        "девяносто",
    ]
    hundreds = [
        "",
        "сто",
        "двести",
        "триста",
        "четыреста",
        "пятьсот",
        "шестьсот",
        "семьсот",
        "восемьсот",
        "девятьсот",
    ]
    groups = [
        (1_000_000_000, ("миллиард", "миллиарда", "миллиардов"), False),
        (1_000_000, ("миллион", "миллиона", "миллионов"), False),
        (1_000, ("тысяча", "тысячи", "тысяч"), True),
    ]

    remainder = value
    parts: list[str] = []
    for divisor, forms, group_feminine in groups:
        chunk = remainder // divisor
        if chunk:
            parts.append(
                _under_thousand_to_words(
                    chunk,
                    feminine=group_feminine,
                    ones_m=ones_m,
                    ones_f=ones_f,
                    teens=teens,
                    tens=tens,
                    hundreds=hundreds,
                )
            )
            parts.append(_select_form(float(chunk), forms))
            remainder %= divisor

    if remainder:
        parts.append(
            _under_thousand_to_words(
                remainder,
                feminine=feminine,
                ones_m=ones_m,
                ones_f=ones_f,
                teens=teens,
                tens=tens,
                hundreds=hundreds,
            )
        )
    return " ".join(part for part in parts if part).strip()


def _under_thousand_to_words(
    value: int,
    *,
    feminine: bool,
    ones_m: list[str],
    ones_f: list[str],
    teens: list[str],
    tens: list[str],
    hundreds: list[str],
) -> str:
    result: list[str] = []
    result.append(hundreds[value // 100])
    rest = value % 100
    if 10 <= rest <= 19:
        result.append(teens[rest - 10])
    else:
        result.append(tens[rest // 10])
        ones = ones_f if feminine else ones_m
        result.append(ones[rest % 10])
    return " ".join(part for part in result if part)
