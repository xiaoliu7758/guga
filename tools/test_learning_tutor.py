# -*- coding: utf-8 -*-
"""learning_tutor 离线测试：测评评分、画像、五阶段计划、理解模型持久化。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.learning_tutor as lt


class LearningTutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lt.DATA_DIR = Path(self.tmp.name)
        lt.PROFILE_PATH = lt.DATA_DIR / 'profile.json'
        lt.ANSWERS_PATH = lt.DATA_DIR / 'pending_answers.json'
        lt.MODEL_PATH = lt.DATA_DIR / 'understanding_model.json'
        lt.SESSION_PATH = lt.DATA_DIR / 'session.json'
        lt.SRS_PATH = lt.DATA_DIR / 'srs.json'

    def tearDown(self):
        self.tmp.cleanup()

    def _answer_all(self, option, confidence='很确定'):
        for q in lt.QUESTIONS:
            lt.record(q['id'], option, confidence)

    def test_questions_shape(self):
        qs = lt.questions()
        self.assertEqual(len(qs), 5)
        for q in qs:
            self.assertEqual(len(q['options']), 3)
            self.assertIn('confidence', q)

    def test_assess_requires_all(self):
        lt.record('q1', 'A', '确定')
        r = lt.assess()
        self.assertFalse(r['ok'])
        self.assertEqual(r['done'], 1)

    def test_all_A_high_confidence_is_results_first(self):
        self._answer_all('A', '很确定')
        r = lt.assess()
        self.assertTrue(r['ok'])
        self.assertEqual(r['profile']['primary'], 'results_first')
        self.assertFalse(r['profile']['mixed'])
        self.assertEqual(r['profile']['secondary'], 'thorough')  # B 与 C 并列时取字典序

    def test_confidence_weighting(self):
        # 3 题 A 很确定(1.5×3=4.5)，2 题 B 很确定(1.5×2=3.0) → 主型 A
        for i, q in enumerate(lt.QUESTIONS):
            opt = 'A' if i < 3 else 'B'
            lt.record(q['id'], opt, '很确定')
        r = lt.assess()
        self.assertEqual(r['profile']['primary'], 'results_first')
        self.assertEqual(r['profile']['scores']['results_first'], 4.5)

    def test_mixed_when_scattered(self):
        # 5 题均匀分布 A/B/C → 浓度低，判混合
        for i, q in enumerate(lt.QUESTIONS):
            lt.record(q['id'], 'ABC'[i % 3], '确定')
        r = lt.assess()
        self.assertTrue(r['profile']['mixed'])

    def test_plan_stages(self):
        self._answer_all('B', '确定')
        lt.assess()
        p = lt.plan('学懂递归')
        self.assertEqual(len(p['stages']), 5)
        self.assertEqual([s['stage'] for s in p['stages']], lt.STAGES)
        self.assertEqual(p['style'], '细嚼稳扎型')

    def test_stage_roundtrip(self):
        lt.set_stage('teach')
        self.assertEqual(lt.current_stage(), 'teach')
        with self.assertRaises(ValueError):
            lt.set_stage('bogus')

    def test_model_persistence(self):
        lt.update_model('递归', 'known', '分不清递归和迭代')
        lt.update_model('递归', 'mastered')
        s = lt.model_status()
        self.assertEqual(s['total'], 1)
        self.assertIn('递归', s['mastered'])
        self.assertIn('分不清递归和迭代', s['with_notes']['递归'])

    def test_invalid_record(self):
        with self.assertRaises(ValueError):
            lt.record('q9', 'A', '确定')
        with self.assertRaises(ValueError):
            lt.record('q1', 'D', '确定')
        with self.assertRaises(ValueError):
            lt.record('q1', 'A', '瞎猜')

    def test_fsrs_review_and_due(self):
        # 新概念第一次复习，下次到时会进入 due
        r = lt.review('递归', 'good')
        self.assertEqual(r['concept'], '递归')
        self.assertIn('due', r)
        # 刚复习完不应立即到期（除非 again）
        due = lt.due_reviews()
        self.assertNotIn('递归', due['due'])
        # again 会在短期内再次到期
        r2 = lt.review('递归', 'again')
        self.assertEqual(r2['rating'], 'again')
        with self.assertRaises(ValueError):
            lt.review('递归', '瞎评')


if __name__ == '__main__':
    unittest.main()
