"""Compare sentence splitters on the Korean gold set.

    python scripts/eval_sentence_splitter.py            # rule-based only
    python scripts/eval_sentence_splitter.py --kiwi     # also kiwipiepy (pip install kiwipiepy; LGPL-3.0)

Metrics: exact paragraph match rate and boundary precision/recall/F1 (boundary = end offset of each
sentence except the paragraph end). Whitespace-insensitive.
"""

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from story_core.ingestion.sentences import RuleBasedKoreanSplitter
from tests.sentence_gold import GOLD

Splitter = Callable[[str], list[str]]


def boundaries(paragraph: str, sentences: list[str]) -> set[int]:
    """Character offsets (ignoring spaces) where one sentence ends and another begins."""
    offsets: set[int] = set()
    position = 0
    for sentence in sentences[:-1]:
        position += len(sentence.replace(" ", ""))
        offsets.add(position)
    return offsets


def evaluate(name: str, split: Splitter) -> None:
    exact = tp = fp = fn = 0
    failures: list[tuple[str, list[str], list[str]]] = []
    started = time.perf_counter()
    for paragraph, expected in GOLD:
        predicted = [s.strip() for s in split(paragraph) if s.strip()]
        if predicted == expected:
            exact += 1
        else:
            failures.append((paragraph, expected, predicted))
        gold_b, pred_b = boundaries(paragraph, expected), boundaries(paragraph, predicted)
        tp += len(gold_b & pred_b)
        fp += len(pred_b - gold_b)
        fn += len(gold_b - pred_b)
    elapsed_ms = (time.perf_counter() - started) * 1000
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"\n== {name}")
    print(f"exact {exact}/{len(GOLD)}  boundary P={precision:.3f} R={recall:.3f} F1={f1:.3f}")
    print(f"time {elapsed_ms:.1f} ms")
    for paragraph, expected, predicted in failures:
        print(f"  - {paragraph}\n      expected  {expected}\n      predicted {predicted}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kiwi", action="store_true")
    args = parser.parse_args()

    rule = RuleBasedKoreanSplitter()
    evaluate("rule-based (story_core)", lambda text: [s.text for s in rule.split(text)])

    if args.kiwi:
        from kiwipiepy import Kiwi

        kiwi = Kiwi()
        evaluate("kiwipiepy split_into_sents", lambda text: [s.text for s in kiwi.split_into_sents(text)])


if __name__ == "__main__":
    main()
