"""Build claude_talk/data/loanwords.tsv (English word -> standard katakana) from JMdict.

    python -I scripts/build_loanwords.py path/to/JMdict_e.gz

JMdict_e.gz: http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz (EDRDG, CC BY-SA 4.0).
The output is a derived work under the same licence; its header says so.
"""
from __future__ import annotations

import datetime
import gzip
import os
import sys
from collections import defaultdict
from collections.abc import Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # -I drops the script folder from sys.path; the package lives one up

from claude_talk import kana, loanwords  # noqa: E402

HEADER = (
    "English -> katakana loanwords derived from JMdict (EDRDG, CC BY-SA 4.0, "
    "https://www.edrdg.org/edrdg/licence.html)\n"
    "Built by scripts/build_loanwords.py on {date} from {source}; "
    "kept only where the katakana matches the English pronunciation's consonants\n"
    "and some reading needs the row (the rules or kana.OVERRIDES do not already give it)."
)


def word_forms(table: dict[str, str]) -> list[str]:
    """Every word whose reading can look up a row: the row's own word, its 's
    form, and the dictionary words inflected from it (sentences -> sentence),
    plus the short ones in capitals, which read as letter names."""
    forms = set(table) | {w + "'s" for w in table}
    forms |= {w for w in kana._cmudict() if any(b in table for b in kana._bases(w))}
    forms |= {w.upper() for w in forms if 2 <= len(w.replace("'", "")) <= 5 and w.replace("'", "").isalpha()}
    return sorted(forms)


def prune(table: dict[str, str], words: Iterable[str]) -> dict[str, str]:
    """`table` without the rows no reading needs: a row goes when every word in
    `words` that looks it up still reads the same (kana and accent) without
    it. Lookups are seen by wrapping kana._fixed, which every table lookup
    goes through; a dropped row's readers are re-read and so re-recorded, since
    they now look up other rows (tests -> test)."""
    kept = dict(table)
    readers: dict[str, set[str]] = defaultdict(set)
    real_fixed, real_table = kana._fixed, kana._loanwords

    def read(word: str) -> kana.Reading:
        def spy(low: str) -> str | None:
            readers[low].add(word)
            return real_fixed(low)

        kana._fixed = spy
        try:
            return kana.word_reading(word)
        finally:
            kana._fixed = real_fixed

    kana._loanwords = lambda: kept
    try:
        before = {w: read(w) for w in set(words) | set(table)}
        for row in sorted(table):
            spelling = kept.pop(row)
            if any(read(w) != before[w] for w in sorted(readers[row] | {row})):
                kept[row] = spelling
    finally:
        kana._loanwords = real_table
    return kept


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    src = argv[0]
    opener = gzip.open if src.endswith(".gz") else open
    with opener(src, "rb") as f:
        table = loanwords.build_table(loanwords.iter_entries(f), kana.rule_kana, kana.romaji_to_kana)
    matched = len(table)
    table = prune(table, word_forms(table))
    header = HEADER.format(date=datetime.date.today().isoformat(), source=os.path.basename(src))
    loanwords.write_table(table, loanwords.DATA_PATH, header)
    print(f"{len(table)} words ({matched - len(table)} more matched but read the same without a row) -> {loanwords.DATA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
