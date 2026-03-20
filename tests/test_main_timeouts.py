import asyncio
import importlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


class MainTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "1:abc"},
            clear=True,
        )
        self._env.start()
        sys.modules.pop("botapp.main", None)
        self.main = importlib.import_module("botapp.main")

    def tearDown(self) -> None:
        sys.modules.pop("botapp.main", None)
        self._env.stop()
        importlib.invalidate_caches()

    async def test_run_with_timeout_raises_user_friendly_error(self):
        async def _hang() -> None:
            await asyncio.sleep(1)

        with self.assertRaises(self.main.ProcessingTimeoutError) as ctx:
            await self.main._run_with_timeout(
                _hang(),
                timeout_seconds=0,
                step="tts chunk 1/1",
            )

        self.assertEqual(ctx.exception.step, "tts chunk 1/1")
        self.assertIn("операция зависла", ctx.exception.user_message)
        self.assertIn("Таймаут: 0 сек", ctx.exception.user_message)

    async def test_generate_and_send_audio_reports_timeout_to_user(self):
        message = AsyncMock()
        message.chat.id = 123
        message.from_user.id = 456
        message.answer_audio = AsyncMock()

        status_message = AsyncMock()
        status_message.text = "Старт"
        status_message.message_id = 1
        status_message.edit_text = AsyncMock(
            side_effect=self.main.ProcessingTimeoutError(
                step="tts chunk 1/1", timeout_seconds=1
            )
        )

        with (
            patch.object(self.main, "extract_url", return_value=None),
            patch.object(
                self.main,
                "resolve_input_text",
                AsyncMock(
                    return_value=type(
                        "Resolved", (), {"text": "Небольшой текст", "source": "text"}
                    )()
                ),
            ),
            patch.object(
                self.main, "safe_update_status", AsyncMock(return_value=status_message)
            ) as safe_update_status,
            patch.object(self.main, "event_logger") as event_logger,
            patch.object(
                self.main,
                "tts_provider",
                type(
                    "Provider",
                    (),
                    {"synthesize": AsyncMock(side_effect=asyncio.TimeoutError())},
                )(),
            ),
        ):
            event_logger.capture = AsyncMock()
            await self.main._generate_and_send_audio(
                message=message,
                status_message=status_message,
                raw_text="Небольшой текст",
                pdf_path=None,
            )

        self.assertGreaterEqual(safe_update_status.await_count, 2)
        final_call = safe_update_status.await_args_list[-1]
        self.assertIn("операция зависла", final_call.kwargs["text"])
        self.assertIn("tts chunk 1/1", final_call.kwargs["text"])
        message.answer_audio.assert_not_awaited()

    def test_prepare_tts_input_keeps_full_text_when_limit_disabled(self):
        text = "Очень длинный текст " * 5000
        prepared, was_truncated = self.main._prepare_tts_input(text)

        self.assertEqual(prepared, text)
        self.assertFalse(was_truncated)

    def test_resolve_tts_chunk_size_uses_safe_default_for_short_texts(self):
        chunk_size = self.main._resolve_tts_chunk_size("А" * 286)
        self.assertEqual(chunk_size, 220)

    async def test_generate_and_send_audio_processes_text_longer_than_old_limit(self):
        long_text = " ".join(["Предложение."] * 7000)
        normalized_text = " ".join(long_text.split()).strip()

        message = AsyncMock()
        message.chat.id = 123
        message.from_user.id = 456
        message.answer_audio = AsyncMock()

        status_message = AsyncMock()
        status_message.text = "Старт"
        status_message.message_id = 1
        status_message.delete = AsyncMock()

        synthesize = AsyncMock(return_value=b"x")

        with (
            patch.object(self.main, "extract_url", return_value=None),
            patch.object(
                self.main,
                "resolve_input_text",
                AsyncMock(
                    return_value=type(
                        "Resolved", (), {"text": long_text, "source": "text"}
                    )()
                ),
            ),
            patch.object(
                self.main, "safe_update_status", AsyncMock(return_value=status_message)
            ),
            patch.object(self.main, "event_logger") as event_logger,
            patch.object(
                self.main,
                "tts_provider",
                type("Provider", (), {"synthesize": synthesize})(),
            ),
        ):
            event_logger.capture = AsyncMock()
            await self.main._generate_and_send_audio(
                message=message,
                status_message=status_message,
                raw_text=long_text,
                pdf_path=None,
            )

        synthesized_text = " ".join(call.args[0] for call in synthesize.await_args_list)
        synthesized_text = " ".join(synthesized_text.split()).strip()
        self.assertEqual(synthesized_text, normalized_text)
        self.assertGreater(len(normalized_text), 60000)
        message.answer_audio.assert_awaited_once()

    async def test_generate_and_send_audio_splits_text_longer_than_220_chars(self):
        text = " ".join(["Короткое предложение."] * 12)

        message = AsyncMock()
        message.chat.id = 123
        message.from_user.id = 456
        message.answer_audio = AsyncMock()

        status_message = AsyncMock()
        status_message.text = "Старт"
        status_message.message_id = 1
        status_message.delete = AsyncMock()

        synthesize = AsyncMock(return_value=b"x")

        with (
            patch.object(self.main, "extract_url", return_value=None),
            patch.object(
                self.main,
                "resolve_input_text",
                AsyncMock(
                    return_value=type(
                        "Resolved", (), {"text": text, "source": "text"}
                    )()
                ),
            ),
            patch.object(
                self.main, "safe_update_status", AsyncMock(return_value=status_message)
            ),
            patch.object(self.main, "event_logger") as event_logger,
            patch.object(
                self.main,
                "tts_provider",
                type("Provider", (), {"synthesize": synthesize})(),
            ),
        ):
            event_logger.capture = AsyncMock()
            await self.main._generate_and_send_audio(
                message=message,
                status_message=status_message,
                raw_text=text,
                pdf_path=None,
            )

        self.assertGreater(len(text), 220)
        self.assertGreater(len(synthesize.await_args_list), 1)
        self.assertTrue(
            all(len(call.args[0]) <= 220 for call in synthesize.await_args_list)
        )


if __name__ == "__main__":
    unittest.main()
