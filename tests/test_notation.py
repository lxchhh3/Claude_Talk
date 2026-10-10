"""English -> AquesTalk phonetic notation ("#>" + hiragana, ' = accent nucleus,
/ = accent-phrase boundary), so the stress lands where English puts it."""
import pytest

from claude_talk.notation import clean_phrase, is_aquestalk_voice, number_words, phonetic, to_notation, to_plain

pytest.importorskip("cmudict")


# ------------------------------------------------------------ sentences
@pytest.mark.parametrize(
    "text,notation",
    [
        # content word = one accent phrase; "the" leans on the next word
        ("Check the log.", "#>ちぇ'っく/ざろ'ぐ。"),
        # a trailing function word leans on the previous one
        ("Thank you.", "#>さ'んくゆー。"),
        # only function words before the content word: one phrase
        ("It is done", "#>いっといずだ'ん。"),
        ("Ready?", "#>れ'でぃ？"),
        ("Done, check the log!", "#>だ'ん、ちぇ'っく/ざろ'ぐ。"),
        ("MCP server", "#>えむしーぴ'ー/さ'ーばー。"),
        ("3 files", "#>すり'ー/ふぁ'いるず。"),
    ],
)
def test_sentences(text, notation):
    assert to_notation(text) == notation


def test_two_sentences_stay_in_one_string():
    assert to_notation("Done. Check the log.") == "#>だ'ん。ちぇ'っく/ざろ'ぐ。"


def test_text_with_japanese_is_left_to_the_normal_reader():
    assert to_notation("テスト passed") is None
    assert to_notation("ビルド成功") is None


def test_nothing_readable_gives_none():
    assert to_notation("...") is None
    assert to_notation("") is None


def test_symbols_and_paths_never_leak_into_the_notation():
    n = to_notation("Edited run_server.py (see claude_talk/text.py)")
    assert n is not None and n.startswith("#>") and n.endswith("。")
    assert not set(n) & set("_.()\\ ")


def test_camel_case_words_are_separate_phrases():
    assert to_notation("ModuleNotFoundError") == "#>も'じゅーる/の'っと/ふぁ'うんど/え'らー。"


def test_hyphenated_words_are_separate_phrases():
    assert to_notation("auto-quant").startswith("#>お'ーと/")


# -------------------------------------------------------------- numbers
@pytest.mark.parametrize(
    "token,words",
    [
        ("0", ["zero"]),
        ("12", ["twelve"]),
        ("40", ["forty"]),
        ("105", ["one", "hundred", "five"]),
        ("159", ["one", "hundred", "fifty", "nine"]),
        ("1,000", ["one", "thousand"]),
        ("2026", ["two", "thousand", "twenty", "six"]),
        ("1000000", ["one", "million"]),
        ("3.25", ["three", "point", "two", "five"]),
        ("12345678901234567", "one two three four five six seven eight nine zero one two three four five six seven".split()),
    ],
)
def test_numbers_are_read_in_english(token, words):
    assert number_words(token) == words


# ------------------------------------------------------- symbol hygiene
@pytest.mark.parametrize(
    "kana,hira",
    [
        ("テスト", "てすと"),
        ("チェ'ック", "ちぇ'っく"),
        ("ヴァリアブル", "ばりあぶる"),  # no ゔ in the engines
        ("ヴォ'イス", "ぼ'いす"),
        ("ティューン", "てゅーん"),
        ("フュージョン", "ひゅーじょん"),
        ("クァルテット", "くあるてっと"),  # くぁ row: AquesTalk2/10 reject it
        ("ヂヅ", "じず"),
        ("ウゥ", "うう"),  # a small kana no engine knows becomes the full one
    ],
)
def test_phonetic_uses_only_syllables_every_engine_accepts(kana, hira):
    assert phonetic(kana) == hira


def test_clean_phrase_drops_what_the_player_rejects():
    assert clean_phrase("ーあ") == "あ"  # no ー at the start of a phrase
    assert clean_phrase("あっっか") == "あっか"  # no double っ
    assert clean_phrase("あっーか") == "あっか"  # no ー right after っ


# ------------------------------------------------------------- helpers
def test_plain_fallback_strips_the_marks():
    assert to_plain("#>ちぇ'っく/ざろ'ぐ。") == "チェック ザログ。"


def test_is_aquestalk_voice():
    assert is_aquestalk_voice("AquesTalk10 F1 (AquesTalkPlayer AquesTalk10 F1E)")
    assert is_aquestalk_voice("Yukkuri Reimu (AquesTalkPlayer れいむ)")
    assert not is_aquestalk_voice("Microsoft Haruka Desktop - Japanese")
    assert not is_aquestalk_voice(None)
