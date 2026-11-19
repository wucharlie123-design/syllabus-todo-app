import importlib.util
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1]/'evaluation/evaluate.py'
spec = importlib.util.spec_from_file_location('event_evaluation', SRC)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class EvaluationTests(unittest.TestCase):
    def test_event_order_does_not_change_result(self):
        gold = [{'title':'講座A','date':'2026-12-05'}, {'title':'講座B','date':'2026-12-05'}]
        score = ev.score_case(gold, list(reversed(gold)))
        self.assertEqual(score['fully_correct_events'], 2)
        self.assertEqual(score['strict_f1'], 1)

    def test_duplicate_prediction_counts_as_extra(self):
        gold = [{'title':'活動','date':'2026-12-05'}]
        score = ev.score_case(gold, gold*2)
        self.assertEqual(score['fully_correct_events'], 1)
        self.assertEqual(len(score['extra_events']), 1)
        self.assertEqual(score['strict_precision'], .5)

    def test_missing_event_included_in_field_denominator(self):
        score = ev.score_case([{'title':'活動','date':'2026-12-05'}], [])
        self.assertEqual(score['strict_recall'], 0)
        self.assertEqual(score['fields']['date']['total'], 1)
        self.assertEqual(score['fields']['date']['correct'], 0)

    def test_no_approximate_credit_for_title_typo(self):
        score = ev.score_case([{'title':'讀書會','date':'2026-12-05'}], [{'title':'讚書會','date':'2026-12-05'}])
        self.assertEqual(score['fully_correct_events'], 0)
        self.assertEqual(score['fields']['title']['correct'], 0)
        self.assertEqual(score['fields']['date']['correct'], 1)

    def test_unknown_empty_fields_do_not_inflate_nonempty_score(self):
        score = ev.score_case([{'title':'活動','date':'2026-12-05','location':''}], [{'title':'活勳','date':'2026-12-05'}])
        self.assertEqual(score['fields']['location']['nonempty_total'], 0)
        self.assertEqual(score['fully_correct_events'], 0)

    def test_extra_events_on_negative_image_are_not_success(self):
        score = ev.score_case([], [{'title':'假的活動','date':'2026-12-05'}])
        self.assertEqual(score['strict_precision'], 0)
        self.assertEqual(len(score['extra_events']), 1)


if __name__ == '__main__':
    unittest.main()
