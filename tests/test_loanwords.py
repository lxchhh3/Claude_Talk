"""Real Japanese loanword spellings for English words, mined from JMdict."""
import importlib.util
import io
import os

import pytest

from claude_talk import kana as kana_mod
from claude_talk import loanwords
from claude_talk.kana import romaji_to_kana, word_reading
from claude_talk.loanwords import build_table, iter_entries, load_table, skeleton, write_table

# a JMdict-shaped fixture, entities and all (the real file defines ~300 of them)
JMDICT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY ik "word containing irregular kana usage">
]>
<JMdict>
<entry><ent_seq>1</ent_seq>
<r_ele><reb>センテンス</reb><re_pri>gai1</re_pri></r_ele>
<sense><pos>&n;</pos><gloss>sentence</gloss></sense>
</entry>
<entry><ent_seq>2</ent_seq>
<k_ele><keb>煙草</keb></k_ele>
<r_ele><reb>タバコ</reb></r_ele>
<sense><pos>&n;</pos><gloss>tobacco</gloss></sense>
</entry>
<entry><ent_seq>3</ent_seq>
<r_ele><reb>レビュー</reb><re_pri>gai1</re_pri></r_ele>
<r_ele><reb>リビュー</reb><re_inf>&ik;</re_inf></r_ele>
<sense><pos>&n;</pos><gloss>review</gloss><gloss>revue (show)</gloss></sense>
</entry>
<entry><ent_seq>4</ent_seq>
<r_ele><reb>アルバイト</reb></r_ele>
<sense><lsource xml:lang="ger">Arbeit</lsource><gloss>part-time job</gloss></sense>
</entry>
<entry><ent_seq>5</ent_seq>
<r_ele><reb>サラリーマン</reb></r_ele>
<sense><lsource ls_wasei="y">salary man</lsource><gloss>office worker</gloss></sense>
</entry>
<entry><ent_seq>6</ent_seq>
<r_ele><reb>マンション</reb></r_ele>
<sense><lsource>mansion</lsource><gloss>apartment</gloss></sense>
</entry>
<entry><ent_seq>7</ent_seq>
<r_ele><reb>チェンジ</reb></r_ele>
<sense><gloss>to change</gloss><gloss>change (e.g. of plans)</gloss></sense>
</entry>
<entry><ent_seq>8</ent_seq>
<r_ele><reb>コンピューター・ウイルス</reb></r_ele>
<sense><gloss>computer virus</gloss></sense>
</entry>
<entry><ent_seq>10</ent_seq>
<k_ele><keb>綺麗</keb></k_ele>
<r_ele><reb>きれい</reb></r_ele>
<r_ele><reb>キレイ</reb></r_ele>
<sense><gloss>pretty</gloss><gloss>clear</gloss></sense>
</entry>
<entry><ent_seq>11</ent_seq>
<k_ele><keb>桜</keb></k_ele>
<r_ele><reb>さくら</reb></r_ele>
<r_ele><reb>サクラ</reb></r_ele>
<sense><gloss>cherry (blossom)</gloss><gloss>sakura</gloss></sense>
</entry>
<entry><ent_seq>9</ent_seq>
<r_ele><reb>デプロイ</reb></r_ele>
<sense><gloss>deployment</gloss><gloss>deploying</gloss></sense>
</entry>
</JMdict>
"""


def _entries():
    return list(iter_entries(io.BytesIO(JMDICT.encode("utf-8"))))


# ------------------------------------------------------------ parsing
def test_single_word_katakana_readings_are_kept():
    readings = [e.readings for e in _entries()]
    assert [("センテンス", True)] in readings
    # a rare kanji spelling (煙草, 頁) does not stop a katakana loanword
    assert [("タバコ", False)] in readings
    assert all("コンピューター・ウイルス" not in [r for r, _ in rs] for rs in readings)
    # ...but a native word that merely has a katakana variant (綺麗: きれい/キレイ) is flagged
    native = [e.readings for e in _entries() if e.native]
    assert [("キレイ", False)] in native and [("サクラ", False)] in native


def test_native_words_count_only_when_the_english_word_is_their_romaji():
    table = build_table(_entries(), {**RULES, "clear": "クリア"}.get, romaji_reading=romaji_to_kana)
    assert table["sakura"] == "サクラ"  # English borrowed it back: sakura
    assert "clear" not in table  # キレイ means clear, it does not come from "clear"
    assert "cherry" not in table


def test_irregular_kana_readings_are_dropped():
    review = next(e for e in _entries() if e.readings and e.readings[0][0] == "レビュー")
    assert review.readings == [("レビュー", True)]


def test_english_candidates_come_from_glosses_and_english_lsource():
    words = {e.readings[0][0]: e.words for e in _entries() if e.readings}
    assert words["センテンス"] == ["sentence"]
    assert words["レビュー"] == ["review", "revue"]  # "(show)" is a note, not part of the word
    assert words["チェンジ"] == ["change"]  # "to " dropped, duplicates merged
    assert "mansion" in words["マンション"]
    assert "アルバイト" not in words  # German source
    assert "サラリーマン" not in words  # wasei-eigo: a Japanese coinage
    # suru-verbs are glossed as gerunds; the bare verb is offered too
    assert words["デプロイ"] == ["deployment", "deploying", "deploy", "deploye"]


# ------------------------------------------------------------ matching
def test_skeleton_ignores_vowels_and_length_but_keeps_consonants():
    assert skeleton("センテンス") == skeleton("センタンス") == "sntns"
    assert skeleton("レビュー") == skeleton("リービュー")
    assert skeleton("チェンジ") == skeleton("チェインジ")
    assert skeleton("パーミッション") == skeleton("パーミシャン")
    assert skeleton("ヴォイス") == skeleton("ボイス")
    assert skeleton("マンション") != skeleton("アパートメント")


RULES = {
    "sentence": "センタンス", "review": "リービュー", "revue": "ラビュー", "change": "チェインジ",
    "apartment": "アパートメント", "mansion": "マンシャン", "tobacco": "タバコー",
    "deploy": "ディプロイ", "deploying": "ディプロイイング", "deployment": "ディプロイマント",
}


def test_build_table_keeps_only_phonetically_matching_pairs():
    table = build_table(_entries(), RULES.get)
    assert table["sentence"] == "センテンス"
    assert table["review"] == "レビュー"
    assert table["change"] == "チェンジ"
    assert table["mansion"] == "マンション"
    assert table["deploy"] == "デプロイ"  # from the gerund gloss
    assert "deployment" not in table and "deploying" not in table  # デプロイ is the clipped form
    assert "apartment" not in table  # gloss is the meaning, not the source word
    assert table["tobacco"] == "タバコ"


def test_build_table_skips_words_without_a_rule_reading():
    table = build_table(_entries(), {"sentence": "センタンス"}.get)
    assert set(table) == {"sentence"}


def test_build_table_rejects_degenerate_matches():
    from claude_talk.loanwords import Entry

    entries = [
        Entry([("イ", True)], ["a"]),  # one letter, no consonants to compare
        Entry([("アッ", False)], ["oh"]),  # empty skeleton, ends in ッ
        Entry([("ゲ", False)], ["ugh"]),  # English starts with a vowel, the kana does not
        Entry([("ルーシ", False)], ["rus'"]),
        Entry([("バッド", False)], ["bad"]),  # fine: Japanese adds the ッ
    ]
    rules = {"a": "ア", "oh": "オー", "ugh": "アグ", "rus'": "ラス", "bad": "バド"}.get
    assert build_table(entries, rules) == {"bad": "バッド"}


def test_build_table_prefers_common_then_closest_reading():
    from claude_talk.loanwords import Entry

    entries = [
        Entry([("コンピュータ", False)], ["computer"]),
        Entry([("コンピューター", False)], ["computer"]),
        Entry([("サーバ", False)], ["server"]),
        Entry([("サーバー", True)], ["server"]),
    ]
    rules = {"computer": "カンピューター", "server": "サーバー"}.get
    table = build_table(entries, rules)
    assert table["computer"] == "コンピューター"  # closer to the rule reading
    assert table["server"] == "サーバー"  # common (re_pri) wins


# ------------------------------------------- pruning (scripts/build_loanwords.py)
def _build_script():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "build_loanwords.py")
    spec = importlib.util.spec_from_file_location("build_loanwords", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRUNE_TABLE = {
    "aardvark": "アードバーク",  # the rules read it the same: dropped
    "claude": "クロード",  # OVERRIDES has it, so the row is never read: dropped
    "sentence": "センテンス",  # the rules say センタンス: kept
    "abacus": "アバカス",  # the rules agree, but "abacus's" reads through the row: kept
}


def test_word_forms_cover_every_word_that_reads_through_a_row():
    forms = set(_build_script().word_forms({"sentence": "センテンス", "abc": "エービーシー"}))
    assert {"sentence", "sentences", "sentence's", "abc", "abc's", "ABC", "ABC'S"} <= forms


def test_prune_keeps_only_the_rows_a_reading_needs():
    build = _build_script()
    kept = build.prune(PRUNE_TABLE, build.word_forms(PRUNE_TABLE))
    assert kept == {"sentence": "センテンス", "abacus": "アバカス"}


def test_prune_leaves_every_reading_unchanged(monkeypatch):
    build = _build_script()
    forms = build.word_forms(PRUNE_TABLE)
    monkeypatch.setattr(kana_mod, "_loanwords", lambda: PRUNE_TABLE)
    before = {w: word_reading(w) for w in forms}
    kept = build.prune(PRUNE_TABLE, forms)
    monkeypatch.setattr(kana_mod, "_loanwords", lambda: kept)
    assert {w: word_reading(w) for w in forms} == before


# ---------------------------------------------------------- file round trip
def test_write_then_load_round_trip(tmp_path):
    path = tmp_path / "loanwords.tsv"
    write_table({"sentence": "センテンス", "review": "レビュー"}, str(path), header="from a test")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# from a test\n")
    assert load_table(str(path)) == {"review": "レビュー", "sentence": "センテンス"}


def test_missing_table_loads_empty(tmp_path):
    assert load_table(str(tmp_path / "nope.tsv")) == {}


# ---------------------------------------------------------- shipped table
@pytest.mark.parametrize(
    "word,kana",
    [
        ("sentence", "センテンス"),
        ("review", "レビュー"),
        ("change", "チェンジ"),
        ("deploy", "デプロイ"),
        ("permission", "パーミッション"),
        ("computer", "コンピューター"),
    ],
)
def test_shipped_table_has_the_standard_loanwords(word, kana):
    assert loanwords.table().get(word) == kana


def test_shipped_table_credits_jmdict():
    with open(loanwords.DATA_PATH, encoding="utf-8") as f:
        head = f.readline()
    assert "JMdict" in head and "CC BY-SA" in head
