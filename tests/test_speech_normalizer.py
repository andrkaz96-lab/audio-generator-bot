import unittest

from botapp.tts.speech_normalizer import normalize_for_speech


class SpeechNormalizerTests(unittest.TestCase):
    def test_required_examples_preserve_meaning(self):
        cases = {
            "В 2025 году OpenAI показала рост на 12.5%.": (
                "две тысячи двадцать пять",
                "оупен эй ай",
                "двенадцать целых пять десятых процента",
            ),
            "NVIDIA RTX 5090 и AI/ML-сервисы.": (
                "энвидиа",
                "эр ти икс",
                "пять тысяч девяносто",
                "эй ай и эм эль",
            ),
            "Температура выросла до 12°C, скорость — 5 км/ч.": (
                "двенадцать градусов Цельсия",
                "пять километров в час",
            ),
            "Компания потратила $20 млн и €15 млн.": (
                "двадцать миллионов долларов",
                "пятнадцать миллионов евро",
            ),
            "Доля составила 1/4 рынка.": ("одна четверть",),
            "Используется Wi‑Fi 6 и USB-C.": (
                "вай фай шесть",
                "ю эс би си",
            ),
            "Версия GPT-4.1 доступна через API.": (
                "джи пи ти четыре целых одна десятая",
                "эй пи ай",
            ),
        }

        for source, expected_parts in cases.items():
            with self.subTest(source=source):
                normalized = normalize_for_speech(source)
                for expected in expected_parts:
                    self.assertIn(expected, normalized)

    def test_quotes_and_mixed_script_are_not_dropped(self):
        normalized = normalize_for_speech(
            'Цитата: "Revenue вырос до $20 млн в Q4 2025 и Wi-Fi 6 стал стандартом".'
        )

        self.assertIn("ревенуе", normalized)
        self.assertIn("двадцать миллионов долларов", normalized)
        self.assertIn("кью четыре", normalized)
        self.assertIn("две тысячи двадцать пять", normalized)
        self.assertIn("вай фай шесть", normalized)

    def test_dates_ranges_and_units_are_verbalized(self):
        normalized = normalize_for_speech(
            "Релиз вышел 2025-03-15, диапазон 5-7 дней, размер 3.14 м и температура -5°C."
        )

        self.assertIn("пятнадцать марта две тысячи двадцать пять года", normalized)
        self.assertIn("от пяти до семи", normalized)
        self.assertIn("три целых четырнадцать сотых метра", normalized)
        self.assertIn("минус пять градусов Цельсия", normalized)


if __name__ == "__main__":
    unittest.main()
