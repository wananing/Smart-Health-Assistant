"""Deterministic tests for render / shortcuts / turns / the summary card."""
import unittest
from datetime import datetime, timedelta, timezone

from voice.gateway import build_clinic_summary
from voice.render import (
    DISCLAIMER,
    LeadCutter,
    RunOutcome,
    normalize_for_speech,
    plan_conclusion,
    plan_for_outcome,
    plan_interrupt,
    pre_speech_check,
    split_sentences,
)
from voice.shortcuts import classify, is_backchannel, is_repeat_request
from voice.turns import NoHearLadder, TurnTrace, looks_unfinished


class NormalisationTests(unittest.TestCase):
    def test_markdown_and_emoji_are_stripped(self):
        self.assertEqual(normalize_for_speech("⚠️ **请注意**：\n- 多喝水"), "请注意： 多喝水")

    def test_numbers_units_and_hotlines_are_spelled_as_read(self):
        cases = {
            "体温38.5℃": "体温三十八点五摄氏度",
            "请拨打120": "请拨打幺二零",
            "每次10mg": "每次十毫克",
            "3-5天": "三到五天",
            "占15%": "占百分之十五",
            "血压120/80mmHg": "血压一百二十/八十毫米汞柱",
            "2005年": "二零零五年",
            "1005次": "一千零五次",
        }
        for raw, spoken in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_for_speech(raw), spoken)

    def test_hotlines_are_read_as_hotlines_only_in_context(self):
        hotline = {
            "请立即拨打120": "请立即拨打幺二零",
            "马上打120叫救护车": "马上打幺二零叫救护车",
            "急救电话120": "急救电话幺二零",
            "报警请打110": "报警请打幺幺零",
            "火警电话是119": "火警电话是幺幺九",
            "呼叫120": "呼叫幺二零",
            "120急救车会来": "幺二零急救车会来",
        }
        number = {
            "布洛芬120mg": "布洛芬一百二十毫克",
            "心率120次": "心率一百二十次",
            "100-120": "一百到一百二十",
            "心率100-120次": "心率一百到一百二十次",
            "血压120/80mmHg": "血压一百二十/八十毫米汞柱",
            "喝了120毫升": "喝了一百二十毫升",
            "体重110斤": "体重一百一十斤",
            "共119人": "共一百一十九人",
        }
        for table in (hotline, number):
            for raw, spoken in table.items():
                with self.subTest(raw=raw):
                    self.assertEqual(normalize_for_speech(raw), spoken)

    def test_sentences_split_on_final_punctuation(self):
        self.assertEqual(split_sentences("好的。还有吗？没有了"), ["好的。", "还有吗？", "没有了"])


class PreSpeechCheckTests(unittest.TestCase):
    def test_absolute_diagnosis_is_never_spoken(self):
        for text in ("您得了肺炎。", "可以确诊为胃炎", "你患有高血压"):
            with self.subTest(text=text):
                self.assertFalse(pre_speech_check(text).ok)

    def test_hedges_that_defer_to_a_doctor_are_allowed(self):
        # Measured live: "…具体以临床医生诊断为准" contains "诊断为" but is a hedge.
        self.assertTrue(pre_speech_check("建议尽快到神经内科就诊，具体以临床医生诊断为准。").ok)
        self.assertTrue(pre_speech_check("最终以医院确诊为准。").ok)
        self.assertFalse(pre_speech_check("医生诊断为偏头痛，以复查结果为准。").ok)

    def test_a_conclusion_must_carry_the_disclaimer(self):
        self.assertFalse(pre_speech_check("建议去呼吸内科。", requires_disclaimer=True).ok)
        self.assertTrue(pre_speech_check(f"建议去呼吸内科。{DISCLAIMER}", requires_disclaimer=True).ok)

    def test_plans(self):
        self.assertEqual(plan_interrupt("followup", "咳嗽几天了？").sentences, ("咳嗽几天了？",))
        self.assertEqual(plan_interrupt("confirm", "对吗？").speak_mode, "confirm")
        good = plan_conclusion({"summary": "建议尽快到呼吸内科就诊"})
        self.assertEqual(good.speak_mode, "conclusion")
        self.assertEqual(good.sentences[-1], DISCLAIMER)
        bad = plan_conclusion({"summary": "您得了肺炎"})
        self.assertEqual((bad.speak_mode, bad.cue_id, bad.reason), ("see_screen", "see_screen", "absolute_diagnosis"))
        self.assertEqual(plan_for_outcome(RunOutcome(handed_off=True)).cue_id, "handoff")
        self.assertEqual(plan_for_outcome(RunOutcome()).cue_id, "see_screen")


class LeadCutterTests(unittest.TestCase):
    def _feed(self, chunks):
        cutter = LeadCutter()
        results = [cutter.feed(chunk) for chunk in chunks]
        decided = [r for r in results if r is not None]
        self.assertLessEqual(len(decided), 1, "decides exactly once")
        return cutter, (decided[0] if decided else None)

    def test_the_first_sentence_is_cut_off_the_token_stream(self):
        cutter, plan = self._feed(["建议您", "今天去神经", "内科看看。", "\n## 分诊建议\n…"])
        self.assertEqual(plan.speak_mode, "conclusion")
        self.assertEqual(plan.sentences[0], "建议您今天去神经内科看看。")
        self.assertEqual(plan.sentences[-1], DISCLAIMER)

    def test_no_usable_lead_falls_back(self):
        for chunks, reason in (
            (["## 分诊建议\n建议去神经内科。"], "no_lead"),
            (["我先帮您评估一下症状。"], "not_a_conclusion"),
            (["您得了偏头痛，建议去神经内科。"], "absolute_diagnosis"),
            (["建议" + "很长" * 40], "no_lead"),
        ):
            with self.subTest(reason=reason):
                _, plan = self._feed(chunks)
                self.assertEqual((plan.speak_mode, plan.reason), ("see_screen", reason))

    def test_undecided_until_the_sentence_ends(self):
        cutter, plan = self._feed(["建议您今天去"])
        self.assertIsNone(plan)
        self.assertFalse(cutter.done)


class ShortcutTests(unittest.TestCase):
    def test_order_emergency_exit_repeat_graph(self):
        self.assertEqual(classify("胸口剧痛，喘不过气").kind, "emergency")
        self.assertEqual(classify("退出").kind, "exit")
        self.assertEqual(classify("再说一遍吧").kind, "repeat")
        self.assertEqual(classify("我想取消明天的预约").kind, "graph")
        self.assertEqual(classify("你说什么时候吃药").kind, "graph")

    def test_repeat_and_backchannel_are_anchored(self):
        self.assertTrue(is_repeat_request("没听清。"))
        self.assertFalse(is_repeat_request("没听清医生说的话怎么办"))
        for text in ("嗯", "嗯嗯", "哦", "好的", "对对对"):
            self.assertTrue(is_backchannel(text), text)
        self.assertFalse(is_backchannel("对，但是很疼"))


class TurnHelpersTests(unittest.TestCase):
    def test_unfinished_signals(self):
        self.assertTrue(looks_unfinished("头疼，然后"))
        self.assertTrue(looks_unfinished("头"))
        self.assertFalse(looks_unfinished("头疼三天了"))

    def test_a_turn_has_exactly_one_terminal_outcome(self):
        trace = TurnTrace(turn_id=1)
        self.assertTrue(trace.finish("interrupted"))
        self.assertFalse(trace.finish("done"))
        self.assertEqual(trace.outcome, "interrupted")
        self.assertTrue(trace.interrupted)

    def test_no_hear_ladder(self):
        ladder = NoHearLadder(elder_mode=False)
        self.assertEqual([ladder.next_step() for _ in range(4)],
                         ["not_heard", "not_heard_button", "push_to_talk", "push_to_talk"])
        ladder.reset()
        self.assertEqual(ladder.next_step(), "not_heard")
        self.assertEqual(NoHearLadder(elder_mode=True).next_step(), "not_heard_button")


class SummaryCardTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
        self.end = self.start + timedelta(minutes=3, seconds=5)

    def test_completed_summary_uses_collected_and_recommendation_only(self):
        data = build_clinic_summary(
            user_info={"name": "测试用户"},
            collected={"chief_complaint": "咳嗽", "duration": "三天", "associated_symptoms": ["发热", "乏力"]},
            recommendation={"summary": "建议尽快就诊。", "departments": ["呼吸内科"], "urgency": "soon", "notes": ["多喝水"]},
            started_at=self.start,
            ended_at=self.end,
        )
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["duration_seconds"], 185)
        self.assertEqual(data["departments"], ["呼吸内科"])
        self.assertEqual(data["facts"][-1], {"field": "associated_symptoms", "label": "是否伴随其他症状", "value": "发热、乏力"})

    def test_hanging_up_before_a_conclusion_is_incomplete(self):
        data = build_clinic_summary(
            user_info={}, collected={"chief_complaint": "头疼"}, recommendation=None,
            started_at=self.start, ended_at=self.end,
        )
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["departments"], [])
        self.assertIsNone(data["urgency"])
        self.assertEqual(data["consultant"], "用户")


if __name__ == "__main__":
    unittest.main()
