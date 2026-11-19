"""Evaluate event extraction without uploading images or requiring dependencies.

Recorded OCR replay measures parsing, not a new OCR run or phone latency.
All expected values must be manually annotated before running evaluation.
"""
import argparse
from difflib import SequenceMatcher
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import time
import unicodedata

FIELDS = ('title', 'date', 'end_date', 'start_time', 'end_time', 'location', 'weekdays')


def norm(value, field=''):
    if field == 'weekdays':
        if isinstance(value, str):
            value = [v.strip() for v in value.split(',') if v.strip()]
        return tuple(sorted(str(v) for v in (value or [])))
    return ''.join(unicodedata.normalize('NFKC', str(value or '')).split())


def align(expected, predicted):
    """Optimal one-to-one matching; duplicate predictions cannot inflate recall."""
    if len(expected) > 15 or len(predicted) > 30:
        raise ValueError('每張圖最多評估15筆標準活動、30筆預測；請拆分測試案例')

    def weight(gold, pred):
        title = norm(gold.get('title'))
        other = norm(pred.get('title'))
        similarity = SequenceMatcher(None, title, other).ratio() if title and other else 0
        same_date = bool(norm(gold.get('date'))) and norm(gold.get('date')) == norm(pred.get('date'))
        if not same_date and similarity < .5:
            return 0
        exact = sum(norm(gold[f], f) == norm(pred.get(f), f) for f in FIELDS if f in gold)
        return exact + similarity + int(same_date)

    @lru_cache(None)
    def best(index, used):
        if index == len(predicted):
            return 0, ()
        score, pairs = best(index + 1, used)
        for target, gold in enumerate(expected):
            if used & (1 << target):
                continue
            value = weight(gold, predicted[index])
            if not value:
                continue
            tail, matches = best(index + 1, used | (1 << target))
            if value + tail > score:
                score, pairs = value + tail, ((target, index),) + matches
        return score, pairs

    pairs = list(best(0, 0)[1])
    return pairs, sorted(set(range(len(expected))) - {g for g, _ in pairs}), sorted(set(range(len(predicted))) - {p for _, p in pairs})


def score_case(expected, predicted):
    pairs, missing, extra = align(expected, predicted)
    by_gold = dict(pairs)
    fields = {}
    errors = []
    strict = 0
    for gi, gold in enumerate(expected):
        pi = by_gold.get(gi)
        pred = predicted[pi] if pi is not None else {}
        annotated = [f for f in FIELDS if f in gold]
        if not annotated:
            raise ValueError('每筆標準答案至少須標註一個欄位')
        good = True
        for field in annotated:
            expected_value, actual = norm(gold[field], field), norm(pred.get(field), field)
            correct = pi is not None and expected_value == actual
            row = fields.setdefault(field, {'correct': 0, 'total': 0, 'nonempty_correct': 0, 'nonempty_total': 0})
            row['total'] += 1
            row['correct'] += int(correct)
            if expected_value:
                row['nonempty_total'] += 1
                row['nonempty_correct'] += int(correct)
            if not correct:
                good = False
                errors.append({'gold_index': gi, 'prediction_index': pi, 'field': field, 'expected': gold[field], 'actual': pred.get(field)})
        strict += int(good)
    # Count extra events explicitly; do not silently drop them from precision.
    precision = strict / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = strict / len(expected) if expected else 1.0
    return {'gold_events': len(expected), 'predicted_events': len(predicted),
            'matched_events': len(pairs), 'missing_events': missing, 'extra_events': extra,
            'fully_correct_events': strict, 'strict_precision': precision, 'strict_recall': recall,
            'strict_f1': 2*precision*recall/(precision+recall) if precision+recall else 0.0,
            'fields': fields, 'errors': errors}


def evaluate(case_dir, parser_path):
    spec = importlib.util.spec_from_file_location('evaluated_mobile_core', parser_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = []
    for path in sorted(Path(case_dir).glob('*.json')):
        case = json.loads(path.read_text(encoding='utf-8'))
        if not case.get('reference_date') or not isinstance(case.get('expected'), list):
            raise ValueError(f'{path}: 必須提供reference_date與expected陣列')
        modes = [('current_parser_replay', None)]
        if case.get('record'):
            recorded = json.loads((path.parent / case['record']).read_text(encoding='utf-8'))
            text = recorded['text']
            modes.insert(0, ('historical_recorded_prediction', recorded['events']))
        else:
            recorded = None
            text = case['text']
        for mode, events in modes:
            elapsed = None
            if events is None:
                started = time.perf_counter()
                events = json.loads(module.extract_events(text, case['reference_date']))['events']
                elapsed = (time.perf_counter()-started)*1000
            score = score_case(case['expected'], events)
            results.append({'id': case['id'], 'split': case['split'], 'input_kind': case['input_kind'],
                            'mode': mode, 'reference_date': case['reference_date'],
                            'parser_ms_host': elapsed, 'ocr_ms_phone': None,
                            'recorded_phone_metrics': recorded.get('metrics') if recorded else None,
                            'score': score, 'predictions': events})
    if not results:
        raise ValueError('找不到測試案例JSON')
    return {'schema_version': 1, 'parser': str(Path(parser_path).resolve()),
            'limitations': ['開發案例與單張實機OCR樣本不是獨立測試集，不能宣稱一般辨識準確率。',
                            '重播使用既有OCR文字，不是重新執行OCR；主機解析耗時不代表手機整體辨識耗時。',
                            '缺少年份的推定不代表圖片原文事實；對外評估應另行標註。',
                            '欄位比對僅做Unicode NFKC與空白正規化，不使用模糊相似度判為正確。'],
            'cases': results}


def markdown(report):
    lines = ['# 辨識評估紀錄', '', *['- '+v for v in report['limitations']], '',
             '| 案例 | 輸入／用途 | 執行方式 | 完全正確活動 | 漏抓／多抓 |',
             '|---|---|---|---|---|']
    for row in report['cases']:
        s = row['score']
        lines.append(f"| {row['id']} | {row['input_kind']} / {row['split']} | {row['mode']} | {s['fully_correct_events']}/{s['gold_events']} | {len(s['missing_events'])}/{len(s['extra_events'])} |")
    for row in report['cases']:
        lines.extend(['', f"## {row['id']} / {row['mode']}", '',
                      f"完整活動 precision={row['score']['strict_precision']:.1%}，recall={row['score']['strict_recall']:.1%}。", '',
                      '| 欄位 | 全部標註正確數 | 非空答案正確數 |', '|---|---|---|'])
        for name, counts in row['score']['fields'].items():
            lines.append(f"| {name} | {counts['correct']}/{counts['total']} | {counts['nonempty_correct']}/{counts['nonempty_total']} |")
        for error in row['score']['errors']:
            lines.append('- '+error['field']+': 預期 '+repr(error['expected'])+'；實際 '+repr(error['actual']))
    return '\n'.join(lines)+'\n'


def main():
    root = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--cases', type=Path, default=root/'cases')
    cli.add_argument('--parser', type=Path, default=root.parent/'app/src/main/python/mobile_core.py')
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    report = evaluate(args.cases, args.parser)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    args.output.with_suffix('.md').write_text(markdown(report), encoding='utf-8')
    print(args.output)
    for case in report['cases']:
        score = case['score']
        print(case['id'], case['mode'], f"完整活動 {score['fully_correct_events']}/{score['gold_events']}; 多抓 {len(score['extra_events'])}")


if __name__ == '__main__':
    main()
