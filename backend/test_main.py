import re
import sys
import types
import unittest

sys.modules.setdefault("imageio_ffmpeg", types.SimpleNamespace())

from main import (
    ASS_LINE_WIDTH,
    MIN_SUBTITLE_SEGMENT_MS,
    split_subtitle_utterance,
    subtitle_text_width,
    utterances_to_ass,
    utterances_to_srt,
    wrap_subtitle_text,
)


SRT_TIMING_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def srt_milliseconds(parts):
    hours, minutes, seconds, millis = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_srt(srt):
    cues = []
    for block in srt.split("\n\n") if srt else []:
        lines = block.splitlines()
        match = SRT_TIMING_RE.fullmatch(lines[1])
        cues.append((srt_milliseconds(match.groups()[:4]), srt_milliseconds(match.groups()[4:]), lines[2:]))
    return cues


class SubtitleFormattingTest(unittest.TestCase):
    def assert_single_line_safe(self, utterances):
        ass = utterances_to_ass(utterances)
        dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
        self.assertTrue(dialogues)
        for dialogue in dialogues:
            rendered = dialogue.split(",", 9)[-1]
            plain = re.sub(r"{[^}]*}", "", rendered)
            self.assertNotIn(r"\N", rendered)
            self.assertNotIn("\n", plain)
            self.assertNotIn("\r", plain)
            self.assertNotIn("，", plain)
            self.assertNotIn("。", plain)
            self.assertLessEqual(subtitle_text_width(plain), ASS_LINE_WIDTH + 0.01)

        srt = utterances_to_srt(utterances)
        cues = parse_srt(srt)
        self.assertEqual(len(cues), len(dialogues))
        self.assertNotIn("，", srt)
        self.assertNotIn("。", srt)
        for _, _, text_lines in cues:
            self.assertEqual(len(text_lines), 1)
            self.assertLessEqual(subtitle_text_width(text_lines[0]), ASS_LINE_WIDTH + 0.01)
        return ass, cues

    def test_text_that_visually_fits_stays_in_one_cue(self):
        # This is far beyond the old character-count budget but narrow in the font.
        text = "iiiiiiiiiiiiiiiiiiii"
        self.assertLess(subtitle_text_width(text), ASS_LINE_WIDTH)
        self.assertEqual(wrap_subtitle_text(text), [text])
        segments = split_subtitle_utterance({"start_time": 321, "end_time": 2321, "text": text})
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0]["start_time"], segments[0]["end_time"]), (321, 2321))

    def test_visual_budget_distinguishes_glyph_classes(self):
        self.assertLess(subtitle_text_width("iiiiiiiiii"), subtitle_text_width("abcdefghij"))
        self.assertLess(subtitle_text_width("abcdefghij"), subtitle_text_width("MWMWMWMWMW"))
        self.assertLess(subtitle_text_width("1234567890"), subtitle_text_width("十个汉字正好在这里呀"))

    def test_long_chinese_is_balanced_without_orphan_tail(self):
        text = "今天我们一起学习英语，理解真实生活场景里的细微区别，并掌握更加自然地道的表达方式。"
        fragments = wrap_subtitle_text(text)
        self.assertGreater(len(fragments), 2)
        cjk_counts = [len(CJK_RE.findall(fragment)) for fragment in fragments]
        self.assertGreaterEqual(min(cjk_counts), 4)
        widths = [subtitle_text_width(fragment) for fragment in fragments]
        self.assertLess(max(widths) - min(widths), ASS_LINE_WIDTH * 0.35)
        _, cues = self.assert_single_line_safe([{"start_time": 1000, "end_time": 9000, "text": text}])
        self.assert_contiguous(cues, 1000, 9000)

    def test_long_english_is_balanced_and_keeps_words_intact(self):
        text = "Practice useful English expressions and understand natural conversations with confidence every day."
        fragments = wrap_subtitle_text(text)
        self.assertGreater(len(fragments), 2)
        self.assertEqual(WORD_RE.findall(" ".join(fragments)), WORD_RE.findall(text))
        self.assertTrue(all(len(WORD_RE.findall(fragment)) >= 2 for fragment in fragments))
        widths = [subtitle_text_width(fragment) for fragment in fragments]
        self.assertGreater(min(widths), ASS_LINE_WIDTH * 0.5)
        _, cues = self.assert_single_line_safe([{"start_time": 0, "end_time": 8000, "text": text}])
        self.assert_contiguous(cues, 0, 8000)

    def test_mixed_language_is_balanced_and_atomic(self):
        text = "今天学习 useful English expressions，并理解它们在真实 conversations 里的自然用法。"
        fragments = wrap_subtitle_text(text)
        self.assertGreater(len(fragments), 2)
        self.assertEqual(WORD_RE.findall(" ".join(fragments)), WORD_RE.findall(text))
        self.assertGreaterEqual(len(CJK_RE.findall(fragments[-1])), 4)
        ass, cues = self.assert_single_line_safe([{"start_time": 200, "end_time": 7200, "text": text}])
        self.assertIn(r"{\c&H00A5FF&}", ass)
        self.assert_contiguous(cues, 200, 7200)

    def test_hidden_punctuation_can_segment_but_never_renders(self):
        text = "先观察这个表达，再理解真实语境。你学会了吗？当然学会了！"
        fragments = wrap_subtitle_text(text)
        self.assertGreater(len(fragments), 1)
        self.assertTrue(any(fragment.endswith(("？", "！")) for fragment in fragments))
        ass, _ = self.assert_single_line_safe([{"start_time": 0, "end_time": 6000, "text": text}])
        self.assertIn("？", ass)
        self.assertIn("！", ass)

    def test_editor_markers_and_line_breaks_are_removed(self):
        utterances = [{
            "start_time": 0,
            "end_time": 5000,
            "text": "这里问【重点】where，你知道[重点]where吗【】？\\N[备注]\n继续练习。",
        }]
        ass, cues = self.assert_single_line_safe(utterances)
        srt = utterances_to_srt(utterances)
        dialogues = "\n".join(line for line in ass.splitlines() if line.startswith("Dialogue:"))
        for marker in ("【重点】", "[重点]", "【】", "[", "]", "【", "】"):
            self.assertNotIn(marker, dialogues)
            self.assertNotIn(marker, srt)
        self.assertGreaterEqual(ass.count(r"{\c&H00A5FF&}where{\c&HFFFFFF&}"), 2)
        self.assert_contiguous(cues, 0, 5000)

    def test_english_highlight_survives_segmentation(self):
        text = "先学习 practical English expressions，然后放进 natural conversations 反复练习。"
        ass, _ = self.assert_single_line_safe([{"start_time": 0, "end_time": 7000, "text": text}])
        color_start = re.escape(r"{\c&H00A5FF&}")
        color_end = re.escape(r"{\c&HFFFFFF&}")
        for word in ("practical", "English", "expressions", "natural", "conversations"):
            self.assertRegex(ass, color_start + r"[^\n]*\b" + word + r"\b[^\n]*" + color_end)

    def test_weighted_timing_is_contiguous_and_has_minimum_when_possible(self):
        utterance = {
            "start_time": 1234,
            "end_time": 11234,
            "text": "先听一个例子，然后学习 practical English expressions，最后放进真实对话里反复练习。",
        }
        segments = split_subtitle_utterance(utterance)
        self.assertGreater(len(segments), 2)
        self.assertEqual(segments[0]["start_time"], utterance["start_time"])
        self.assertEqual(segments[-1]["end_time"], utterance["end_time"])
        for previous, current in zip(segments, segments[1:]):
            self.assertEqual(previous["end_time"], current["start_time"])
        for segment in segments:
            self.assertGreaterEqual(segment["end_time"] - segment["start_time"], MIN_SUBTITLE_SEGMENT_MS)
        _, cues = self.assert_single_line_safe([utterance])
        self.assert_contiguous(cues, 1234, 11234)

    def assert_contiguous(self, cues, expected_start, expected_end):
        self.assertEqual(cues[0][0], expected_start)
        self.assertEqual(cues[-1][1], expected_end)
        for previous, current in zip(cues, cues[1:]):
            self.assertEqual(previous[1], current[0])
            self.assertLessEqual(previous[0], previous[1])
        self.assertLessEqual(cues[-1][0], cues[-1][1])


if __name__ == "__main__":
    unittest.main()
