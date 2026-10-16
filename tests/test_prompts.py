"""System-prompt channel handling: SMS replies must not reference app UI."""

import re
import unittest

from src.prompts.templates import TONE_VARIANTS, system_message_for_tone

_UI_WORDS = re.compile(r"\b(button|tap|click|screen)\b", re.IGNORECASE)


class SystemMessageChannelTest(unittest.TestCase):
    def test_app_prompt_keeps_meeting_button(self):
        for tone in TONE_VARIANTS:
            self.assertIn('"Find a meeting" button', system_message_for_tone(tone))

    def test_sms_prompt_has_no_ui_references(self):
        for tone in TONE_VARIANTS:
            msg = system_message_for_tone(tone, channel="sms")
            self.assertIsNone(_UI_WORDS.search(msg), f"{tone}: {_UI_WORDS.search(msg)}")
            self.assertIn("sobrietycopilot.com", msg)


if __name__ == "__main__":
    unittest.main()
