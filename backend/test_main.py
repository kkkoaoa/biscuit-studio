import re
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("imageio_ffmpeg", types.SimpleNamespace())

from main import (
    ASS_LINE_WIDTH,
    BurnSubtitlesRequest,
    CreateVideoRequest,
    DIALOGUE_PARTNERS,
    MIN_SUBTITLE_SEGMENT_MS,
    SubtitleStatusRequest,
    SubtitleSubmitRequest,
    TaskStatusRequest,
    GenerateScriptRequest,
    build_script_instruction,
    clean_expected_subtitle_text,
    expected_subtitle_text,
    map_dialogue_translations,
    normalize_dialogue_subtitles,
    split_dialogue_utterance,
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


class ScriptModeTest(unittest.TestCase):
    def make_payload(self, **overrides):
        values = {
            "api_key": "test-key-123",
            "topic": "Could you 和 Can you 的语气差异",
            "scene": "咖啡店柜台",
        }
        values.update(overrides)
        return GenerateScriptRequest(**values)

    def test_default_mode_keeps_knowledge_template(self):
        payload = self.make_payload()
        self.assertEqual(payload.content_mode, "knowledge")
        instruction = build_script_instruction(payload)
        self.assertIn("知识讲解约占 70%", instruction)
        self.assertIn("画外成年男声", instruction)
        self.assertNotIn("本条唯一对话伙伴", instruction)

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            self.make_payload(content_mode="lecture")

    def test_dialogue_mode_uses_dialogue_template(self):
        partner = DIALOGUE_PARTNERS[1]
        with patch("main.select_dialogue_partner", return_value=partner):
            instruction = build_script_instruction(self.make_payload(content_mode="dialogue"))
        self.assertIn("采用“先讲一点，再演一遍”的结构", instruction)
        self.assertIn("5～8 轮短对话", instruction)
        self.assertIn("4～6 段连续分镜", instruction)
        self.assertIn("只有当前说话角色动嘴", instruction)
        self.assertIn("不得生成任何文字、字幕、标题、单词、Logo 或水印", instruction)

    def test_each_random_partner_is_fully_locked_and_exclusive(self):
        for partner in DIALOGUE_PARTNERS:
            with self.subTest(partner=partner["name"]):
                with patch("main.select_dialogue_partner", return_value=partner):
                    instruction = build_script_instruction(self.make_payload(content_mode="dialogue"))
                self.assertIn(partner["name"], instruction)
                self.assertIn(partner["appearance"], instruction)
                self.assertIn(partner["voice"], instruction)
                self.assertIn("不得出现第三只动物", instruction)
                for other in DIALOGUE_PARTNERS:
                    if other is not partner:
                        # Examples in the subtitles rule may mention a generic animal name.
                        if other["name"] != "小鸟":
                            self.assertNotIn(other["name"], instruction)


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

    def test_speaker_prefixes_are_removed_only_at_line_start(self):
        source = "\n".join([
            "【小饼干】你好【重点】hello", "[小猫]：轮到我了", "小水獭: 请进",
            "小仓鼠+谢谢", "小鸟＋早上好", "画外男声：开始吧", "旁白: 天亮了",
            "我看见小鸟：它正在唱歌", "今天请小饼干帮忙",
        ])
        cleaned = clean_expected_subtitle_text(source)
        self.assertEqual(cleaned.splitlines(), [
            "你好hello", "轮到我了", "请进", "谢谢", "早上好", "开始吧", "天亮了",
            "我看见小鸟：它正在唱歌", "今天请小饼干帮忙",
        ])
        ass, _ = self.assert_single_line_safe([{"start_time": 0, "end_time": 4000, "text": "【小鸟】：请读【重点】hello，小鸟在窗外。"}])
        plain = re.sub(r"{[^}]*}", "", "\n".join(line for line in ass.splitlines() if line.startswith("Dialogue:")))
        self.assertNotIn("【小鸟】", plain)
        self.assertIn("hello", plain)
        self.assertIn("小鸟在窗外", plain)
        self.assertIn(r"{\c&H00A5FF&}hello{\c&HFFFFFF&}", ass)

    def test_six_to_eight_english_words_that_fit_stay_one_cue(self):
        text = "I am on my way to you"
        self.assertEqual(len(WORD_RE.findall(text)), 7)
        self.assertEqual(wrap_subtitle_text(text), [text])

    def test_long_overflowing_english_splits_without_orphan_tail(self):
        text = "I am on my way and I can help you now"
        fragments = wrap_subtitle_text(text)
        self.assertGreater(len(fragments), 1)
        self.assertTrue(all(subtitle_text_width(fragment) <= ASS_LINE_WIDTH + 0.01 for fragment in fragments))
        self.assertTrue(all(len(WORD_RE.findall(fragment)) >= 4 for fragment in fragments))
        self.assertEqual(WORD_RE.findall(" ".join(fragments)), WORD_RE.findall(text))

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


class BilingualDialogueRegressionTest(unittest.TestCase):
    def test_all_legacy_requests_default_to_knowledge(self):
        self.assertEqual(CreateVideoRequest(api_key="test-key-123", prompt="long enough prompt").content_mode, "knowledge")
        self.assertEqual(TaskStatusRequest(api_key="test-key-123", task_id="task").content_mode, "knowledge")
        self.assertEqual(SubtitleSubmitRequest(video_url="https://example.com/video.mp4").content_mode, "knowledge")
        self.assertEqual(SubtitleStatusRequest(task_id="ata:task").content_mode, "knowledge")
        self.assertEqual(BurnSubtitlesRequest(video_url="https://example.com/video.mp4", utterances=[{"text": "hi"}]).content_mode, "knowledge")

    def test_dialogue_expected_text_excludes_translation_and_speakers(self):
        source = "【小饼干】：Could you help me? ||| 你能帮我吗？\n[小猫]: Of course. ||| 当然可以。"
        normalized = normalize_dialogue_subtitles(source)
        expected = expected_subtitle_text(normalized, "dialogue")
        self.assertEqual(expected, "Could you help me?\nOf course.")
        self.assertNotRegex(expected, r"[\u3400-\u9fff]")
        self.assertNotIn("小饼干", normalized)
        self.assertNotIn("小猫", normalized)

    def test_knowledge_remains_single_line_without_translation(self):
        utterances = [{"start_time": 0, "end_time": 2000, "text": "先学【重点】could you，再看例句。", "translation": "不应显示"}]
        srt = utterances_to_srt(utterances)
        ass = utterances_to_ass(utterances)
        self.assertEqual(len(parse_srt(srt)[0][2]), 1)
        self.assertNotIn("不应显示", srt + ass)
        self.assertNotIn(r"\N", ass)

    def test_dialogue_is_english_first_chinese_second_and_highlighted(self):
        utterances = [{"start_time": 0, "end_time": 2000, "text": "Could you help me?", "translation": "你能帮我吗？"}]
        srt = utterances_to_srt(utterances, "dialogue")
        ass = utterances_to_ass(utterances, "dialogue")
        self.assertEqual(parse_srt(srt)[0][2], ["Could you help me?", "你能帮我吗？"])
        self.assertIn(r"{\c&H00A5FF&}Could you help me{\c&HFFFFFF&}", ass)
        self.assertIn(r"\N{\rDefault\fs40", ass)
        self.assertNotIn("，", srt)
        self.assertNotIn("。", srt)

    def test_mapping_failure_drops_translation_safely(self):
        pairs = "Could you help me? ||| 你能帮我吗？"
        mapped = map_dialogue_translations([{"start_time": 0, "end_time": 1000, "text": "Totally unrelated words"}], pairs)
        self.assertEqual(mapped[0]["translation"], "")
        self.assertNotIn(r"\N", utterances_to_ass(mapped, "dialogue"))

    def test_long_dialogue_splits_pairs_without_orphans(self):
        utterance = {
            "start_time": 0,
            "end_time": 6000,
            "text": "Could you please help me find the nearest train station before it gets dark tonight",
            "translation": "天黑之前你能帮我找到最近的火车站吗",
        }
        segments = split_dialogue_utterance(utterance)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(segment["translation"] for segment in segments))
        self.assertTrue(all(len(CJK_RE.findall(segment["translation"])) >= 2 for segment in segments))
        srt = utterances_to_srt([utterance], "dialogue")
        self.assertTrue(all(len(lines) == 2 for _, _, lines in parse_srt(srt)))

    def test_short_dialogue_does_not_split(self):
        utterance = {"start_time": 0, "end_time": 2000, "text": "I am on my way to you", "translation": "我正在去找你的路上"}
        self.assertEqual(len(split_dialogue_utterance(utterance)), 1)


if __name__ == "__main__":
    unittest.main()
