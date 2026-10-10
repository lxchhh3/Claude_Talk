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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # -I drops the script folder from sys.path; the package lives one up

from claude_talk import kana, loanwords  # noqa: E402

HEADER = (
    "English -> katakana loanwords derived from JMdict (EDRDG, CC BY-SA 4.0, "
    "https://www.edrdg.org/edrdg/licence.html)\n"
    "Built by scripts/build_loanwords.py on {date} from {source}; "
    "kept only where the katakana matches the English pronunciation's consonants."
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    src = argv[0]
    opener = gzip.open if src.endswith(".gz") else open
    with opener(src, "rb") as f:
        table = loanwords.build_table(loanwords.iter_entries(f), kana.rule_kana, kana.romaji_to_kana)
    header = HEADER.format(date=datetime.date.today().isoformat(), source=os.path.basename(src))
    loanwords.write_table(table, loanwords.DATA_PATH, header)
    print(f"{len(table)} words -> {loanwords.DATA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
