"""English -> katakana transliteration for the yukkuri voice (Japanese-accented
English, not translation)."""
import pytest

from claude_talk import kana as kana_mod
from claude_talk.kana import (
    OVERRIDES,
    Reading,
    arpabet_to_kana,
    has_latin,
    romaji_to_kana,
    rule_kana,
    spell_letters,
    transliterate,
    word_reading,
    word_to_kana,
)

LOANS = {
    "sentence": "センテンス", "review": "レビュー", "change": "チェンジ",
    "computer": "コンピューター", "claude": "クラウド",
}


@pytest.fixture
def no_loanwords(monkeypatch):
    monkeypatch.setattr(kana_mod, "_loanwords", lambda: {})


@pytest.fixture
def loans(monkeypatch):
    monkeypatch.setattr(kana_mod, "_loanwords", lambda: LOANS)


# --------------------------------------------------------------- has_latin
def test_has_latin():
    assert has_latin("tests passed") is True
    assert has_latin("テスト 3 件") is False
    assert has_latin("") is False


# ------------------------------------------------------- arpabet rule engine
@pytest.mark.parametrize(
    "arpabet,kana",
    [
        ("T EH1 S T", "テスト"),
        ("T EH1 S T S", "テスツ"),
        ("P AE1 S T", "パスト"),
        ("F EY1 L D", "フェイルド"),
        ("B IH1 L D", "ビルド"),
        ("S ER1 V ER0", "サーバー"),
        ("D AW1 N L OW2 D", "ダウンロード"),
        ("EH1 R ER0", "エラー"),
        ("F AY1 L", "ファイル"),
        ("TH AE1 NG K S", "サンクス"),
        ("HH AH0 L OW1", "ハロー"),
        ("CH EH1 K", "チェック"),
        ("S T AA1 P", "ストップ"),
        ("L AO1 G", "ログ"),
        ("Y EH1 S", "イェス"),
        ("W IH1 N D OW0 Z", "ウィンドーズ"),
        ("K AH0 M P Y UW1 T ER0", "カンピューター"),
        ("R EH1 D IY0", "レディー"),
        ("M AO1 R N IH0 NG", "モーニング"),
        ("D AH1 N", "ダン"),
        ("G IH1 T HH AH0 B", "ギットハブ"),
        ("K Y UW1 B", "キューブ"),
        ("JH EY1 S AH0 N", "ジェイサン"),
        # final m is ム; only a labial makes it ン
        ("T AY1 M", "タイム"),
        ("G EY1 M", "ゲイム"),
        # r-coloured vowel before another vowel: the r starts the next mora
        ("M EH1 M ER0 IY0", "メマリー"),
        ("ER0 EY1", "アレイ"),
        # kw + vowel is written ク + vowel (リクエスト, クイック)
        ("R IH0 K W EH1 S T", "リクエスト"),
        ("K W IH1 K", "クイック"),
        # glides into -er: プレイヤー, パワー
        ("P L EY1 ER0", "プレイヤー"),
        ("P AW1 ER0", "パワー"),
        # final -ds is ズ like -ts is ツ
        ("W ER1 D Z", "ワーズ"),
        ("W AH1 T S", "ワッツ"),  # -ts after a stressed short vowel doubles like a stop
    ],
)
def test_arpabet_rules(arpabet, kana):
    assert arpabet_to_kana(arpabet.split()) == kana


# --------------------------------------------------------------- word level
def test_overrides_win_over_the_dictionary():
    assert OVERRIDES["claude"] == "クロード"
    assert word_to_kana("Claude") == "クロード"
    assert word_to_kana("talk") == "トーク"
    assert word_to_kana("pytest") == "パイテスト"


def test_dictionary_words_go_through_the_rules(no_loanwords):
    pytest.importorskip("cmudict")
    assert word_to_kana("computer") == "カンピューター"
    assert word_to_kana("download") == "ダウンロード"
    assert word_to_kana("GitHub") == "ギットハブ"


def test_acronyms_and_short_unknowns_are_spelled():
    assert spell_letters("mcp") == "エムシーピー"
    assert word_to_kana("MCP") == "エムシーピー"
    assert word_to_kana("GPU") == "ジーピーユー"
    assert word_to_kana("xq") == "エックスキュー"  # unknown, too short to guess


@pytest.mark.parametrize(
    "word,kana",
    [
        ("zorblat", "ゾルブラト"),
        ("numpy", "ヌンピ"),
        ("conda", "コンダ"),
        ("sudachi", "スダチ"),
        ("winsound", "ウィンソウンド"),
        ("hatto", "ハット"),
    ],
)
def test_romaji_fallback_reads_unknown_words(word, kana):
    assert romaji_to_kana(word) == kana


def test_unknown_long_word_uses_romaji_fallback():
    assert word_to_kana("zorblat") == "ゾルブラト"


# ------------------------------------------------------------- whole text
def test_transliterate_sentence_with_punctuation_and_digits():
    assert transliterate("All tests passed. 3 files, really?") == "オール テスツ パスト。 3 ファイルズ、 リアリー？"


def test_transliterate_leaves_japanese_and_decimals_alone():
    assert transliterate("テストが passed しました。loss 0.25") == "テストが パスト しました。ロス 0.25"


def test_transliterate_project_label_and_hyphens():
    assert transliterate("Claude Talk") == "クロード トーク"
    assert transliterate("auto-quant") == "オート クウォント"


def test_transliterate_possessive():
    assert transliterate("Kevin's PC") == "ケビンズ ピーシー"


def test_transliterate_text_without_latin_is_unchanged():
    assert transliterate("ビルド成功。") == "ビルド成功。"


def test_common_notification_words_read_as_loanwords():
    assert word_to_kana("moment") == "モーメント"
    assert word_to_kana("minute") == "ミニット"
    assert word_to_kana("result") == "リザルト"
    assert word_to_kana("query") == "クエリー"
    assert word_to_kana("window") == "ウィンドウ"
    assert word_to_kana("today") == "トゥデイ"
    assert word_to_kana("backtest") == "バックテスト"
    extra = {"four": "フォー", "year": "イヤー", "hmm": "フーム", "civ": "シブ", "language": "ランゲージ",
             "from": "フロム", "capital": "キャピタル"}
    for word, kana in extra.items():
        assert word_to_kana(word) == kana


# ------------------------------------------------------ loanword spellings
def test_rule_kana_is_the_dictionary_reading_or_none():
    pytest.importorskip("cmudict")
    assert rule_kana("sentence") == "センタンス"
    assert rule_kana("zorblat") is None


def test_loanword_spelling_beats_the_rules(loans):
    assert word_to_kana("sentence") == "センテンス"
    assert word_to_kana("Review") == "レビュー"


def test_overrides_still_beat_the_loanword_table(loans):
    assert word_to_kana("claude") == "クロード"


@pytest.mark.parametrize(
    "word,kana",
    [
        ("sentences", "センテンシズ"),
        ("changed", "チェンジド"),
        ("changes", "チェンジズ"),
        ("reviews", "レビューズ"),
        ("reviewed", "レビュード"),
        ("computers", "コンピューターズ"),
    ],
)
def test_inflected_forms_reuse_the_loanword(loans, word, kana):
    pytest.importorskip("cmudict")
    assert word_to_kana(word) == kana


# ----------------------------------------------------------------- accent
# Reading.accent = index in .kana right after the mora carrying the English
# primary stress (where the pitch falls), or None for no stress.
@pytest.mark.parametrize(
    "word,reading",
    [
        ("computer", ("コンピューター", 4)),  # comPUter -> コンピュ'ーター
        ("sentence", ("センテンス", 1)),  # SENtence -> セ'ンテンス
        ("review", ("レビュー", 3)),  # reVIEW -> レビュ'ー
        ("changed", ("チェンジド", 2)),  # inflection keeps the base accent
    ],
)
def test_loanwords_carry_the_english_stress(loans, word, reading):
    pytest.importorskip("cmudict")
    assert word_reading(word) == reading


@pytest.mark.parametrize(
    "word,reading",
    [
        ("download", ("ダウンロード", 1)),  # DOWNload, from the rules directly
        ("thank", ("サンク", 1)),
        ("server", ("サーバー", 1)),  # override spelling, dictionary stress
        ("talk", ("トーク", 1)),  # stress lands on ト even though the rules said トック
        ("claude", ("クロード", 2)),
        ("api", ("エーピーアイ", 5)),  # a-p-EYE
    ],
)
def test_stress_from_the_dictionary(no_loanwords, word, reading):
    pytest.importorskip("cmudict")
    assert word_reading(word) == reading


def test_unstressed_words_have_no_accent(no_loanwords):
    pytest.importorskip("cmudict")
    assert word_reading("the").accent is None


def test_spelled_acronyms_stress_the_last_letter(no_loanwords):
    assert word_reading("MCP") == Reading("エムシーピー", 5)  # em-see-PEE
    assert word_reading("xq") == Reading("エックスキュー", 6)  # ...キュ'ー: small ュ stays with its mora


def test_short_all_caps_words_are_spelled_even_when_the_dictionary_knows_them():
    assert word_to_kana("PR") == "ピーアール"
    assert word_to_kana("IT") == "アイティー"
    assert word_to_kana("OK") == "オーケー"  # overrides still win
    assert word_to_kana("A") == "ア"  # a sentence-initial article is not a letter


def test_camel_case_is_read_word_by_word():
    pytest.importorskip("cmudict")
    assert transliterate("ModuleNotFoundError") == "モジュール ノット ファウンド エラー"
    assert transliterate("PyTorch") == "パイ トーチ"


@pytest.mark.parametrize(
    "word,kana",
    [
        # unstressed endings follow the spelling, as Japanese loanwords do
        ("edited", "エディテッド"), ("added", "アデッド"), ("loaded", "ローデッド"),  # -ited -ded
        ("ticket", "ティケット"), ("budget", "バジェット"), ("internet", "インターネット"),  # -et
        ("usage", "ユーセージ"), ("damage", "ダメージ"),  # -age
        ("climate", "クライメート"), ("private", "プライベート"),  # -ate
        ("function", "ファンクション"), ("version", "バージョン"),  # -tion / -sion
        ("deployment", "ディプロイメント"),  # -ment
        ("happiness", "ハピーネス"), ("wireless", "ワイヤーレス"),  # -ness / -less
        ("successful", "サクセスフル"),  # -ful
        ("possible", "ポシブル"), ("available", "アベイラブル"), ("simple", "シンプル"),  # -ible -able -le
        ("model", "モデル"), ("symbol", "シンボル"), ("pencil", "ペンシル"),  # -el -ol -il
        ("chosen", "チョーズン"), ("token", "トークン"), ("golden", "ゴールデン"),  # -en
        ("person", "パーソン"), ("season", "シーズン"),  # -on
        ("levels", "レベルズ"), ("damages", "ダメージズ"),  # endings under -s
        ("hearing", "ヒアリング"), ("sharing", "シェアリング"),  # the r comes back before -ing
        # final r after a front/rounded vowel is ア; "ar" before a consonant is アー
        ("care", "ケア"), ("clear", "クリア"), ("sure", "シュア"), ("more", "モア"), ("door", "ドア"),
        ("for", "フォー"), ("car", "カー"), ("start", "スタート"), ("market", "マーケット"),
    ],
)
def test_spelling_guides_the_unstressed_vowels(no_loanwords, word, kana):
    pytest.importorskip("cmudict")
    assert word_to_kana(word) == kana


@pytest.mark.parametrize(
    "word,kana",
    [
        ("attacking", "アタッキング"),  # the base's ッ stays, its final mora merges with -ing
        ("committed", "コミッテッド"),
        ("requested", "リクエステッド"),
        ("plans", "プランズ"),
        ("games", "ゲームズ"),
        ("scoring", "スコアリング"),
        ("seconds", "セカンズ"),
        ("edited", "エディテッド"),  # ed-it is unstressed before the t: no ッ (unlike com-MIT)
        ("it's", "イッツ"),  # 's merges like any other ending
    ],
)
def test_inflections_merge_the_last_consonant(monkeypatch, word, kana):
    pytest.importorskip("cmudict")
    table = {"attack": "アタック", "request": "リクエスト", "plan": "プラン", "game": "ゲーム",
             "score": "スコア", "second": "セカンド", "edit": "エディット"}
    monkeypatch.setattr(kana_mod, "_loanwords", lambda: table)
    assert word_to_kana(word) == kana


def test_unknown_words_stress_the_first_mora(no_loanwords):
    assert word_reading("zorblat") == Reading("ゾルブラト", 1)
    assert word_reading("sudachi") == Reading("スダチ", 1)
