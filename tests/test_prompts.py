"""System-prompt channel handling: SMS replies must not reference app UI."""

import re
import unittest

from src.prompts.templates import TONE_VARIANTS, system_message_for_tone

_UI_WORDS = re.compile(r"\b(button|tap|click|screen)\b", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}")


class SystemMessageChannelTest(unittest.TestCase):
    def test_app_prompt_keeps_meeting_button(self):
        for tone in TONE_VARIANTS:
            self.assertIn('"Find a meeting" button', system_message_for_tone(tone))

    def test_sms_prompt_has_no_ui_references(self):
        for tone in TONE_VARIANTS:
            msg = system_message_for_tone(tone, channel="sms")
            self.assertIsNone(_UI_WORDS.search(msg), f"{tone}: {_UI_WORDS.search(msg)}")
            self.assertIn("sobrietycopilot.com", msg)

    def test_only_the_real_helpline_number(self):
        # The model invents "AA hotline" numbers unless given exactly one.
        for tone in TONE_VARIANTS:
            for channel in ("app", "sms"):
                msg = system_message_for_tone(tone, channel=channel)
                self.assertEqual(set(_PHONE.findall(msg)), {"(212) 647-1680"}, (tone, channel))

    def test_crisis_steers_to_helpline_or_in_person_meeting_only(self):
        for tone in TONE_VARIANTS:
            for channel in ("app", "sms"):
                msg = system_message_for_tone(tone, channel=channel)
                self.assertIn("FIRST sentence must strongly urge them to call", msg)
                self.assertIn("in-person A.A. meeting today", msg)
                self.assertIn("never suggest 988", msg)


if __name__ == "__main__":
    unittest.main()
