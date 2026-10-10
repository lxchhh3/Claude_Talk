import pytest

from claude_talk.text import (
    DEFAULT_VOICES,
    clean_text,
    detect_language,
    pick_voice,
    truncate,
)

AVAIL = [
    "Microsoft David Desktop - English (United States)",
    "Microsoft Zira Desktop - English (United States)",
    "Microsoft Haruka Desktop - Japanese",
    "Microsoft Huihui Desktop - Chinese (Simplified)",
    "Mei (Open JTalk)",
    "Yukkuri Reimu (AquesTalkPlayer れいむ)",
    "Yukkuri Marisa (AquesTalkPlayer まりさ)",
]
DAVID, ZIRA, HARUKA, HUIHUI, MEI, YUKKURI, MARISA = AVAIL


# ---------------------------------------------------------------- clean_text
def test_clean_strips_headers_emphasis_and_inline_code():
    s = "## Done\n\n**All 12 tests** passed, see `run.log`."
    assert clean_text(s) == "Done. All 12 tests passed, see run.log."


def test_clean_replaces_fenced_code_block_with_marker():
    s = "Fixed it:\n```python\nprint(1)\n```\nrerun now"
    assert clean_text(s) == "Fixed it: (code omitted) rerun now."


def test_clean_bullets_become_sentences():
    assert clean_text("- first\n* second\n1. third") == "first. second. third."


def test_clean_markdown_links_keep_text_and_bare_urls_become_link():
    s = "See [the docs](https://example.com/a/b) or https://foo.bar/baz?q=1 later"
    assert clean_text(s) == "See the docs or link later."


def test_clean_collapses_whitespace_and_keeps_existing_punctuation():
    assert clean_text("a   b\t c!") == "a b c!"


def test_clean_drops_chinese_text():
    # the user does not want to hear any Chinese; no kana => Chinese
    assert clean_text("测试完成。\n请检查") == ""
    assert clean_text("done 完成 now") == "done now."
    assert clean_text("fullwidth：colon！bang") == "fullwidth colon bang."
    assert clean_text("한국어 too") == "too."  # no Korean voice installed either


def test_clean_keeps_japanese_when_kana_present_and_ends_with_maru():
    assert clean_text("テスト完了。\n次へ") == "テスト完了。 次へ。"
    assert clean_text("done テスト完了") == "done テスト完了。"
    assert clean_text("完了しました。") == "完了しました。"
    assert clean_text("テスト完了 ok, 한국어 too") == "テスト完了 ok, too。"
    assert clean_text("- ビルド成功\n- テスト成功") == "ビルド成功。 テスト成功。"


def test_clean_empty_input_is_empty():
    assert clean_text("   \n```\nx\n```\n") == "(code omitted)."
    assert clean_text("   \n\n") == ""


def test_clean_quoted_sentence_is_already_terminated():
    assert clean_text('He said "done."') == 'He said "done."'
    assert clean_text("Done (see log)") == "Done (see log)."


def test_clean_leaves_windows_paths_and_underscored_names_alone():
    s = "Edited D:\\2files\\tools\\run_server.py and claude_talk.text"
    assert clean_text(s) == "Edited D:\\2files\\tools\\run_server.py and claude_talk.text."


# ------------------------------------------------------------------ truncate
def test_truncate_short_text_untouched():
    assert truncate("hi there.", 50) == ("hi there.", False)


def test_truncate_cuts_at_last_sentence_end_before_limit():
    t = "First sentence. Second sentence is longer. Third one."
    assert truncate(t, 30) == ("First sentence.", True)


def test_truncate_falls_back_to_word_boundary():
    t = "word " * 20
    cut, flag = truncate(t.strip(), 23)
    assert flag is True
    assert cut == "word word word word"


def test_truncate_japanese_sentence_end():
    assert truncate("今日は完了。明日続き。", 8) == ("今日は完了。", True)


def test_truncate_hard_cut_when_no_boundary():
    assert truncate("x" * 50, 10) == ("x" * 10, True)


# ----------------------------------------------------------- detect_language
@pytest.mark.parametrize(
    "text,lang",
    [
        ("hello there", "en"),
        ("测试完成", "zh"),
        ("テスト完了", "ja"),
        ("完了しました", "ja"),
        ("done 完成", "zh"),
        ("混合 テキスト", "ja"),
        ("", "en"),
    ],
)
def test_detect_language(text, lang):
    assert detect_language(text) == lang


# ---------------------------------------------------------------- pick_voice
def test_default_voice_table_prefers_reimu_then_mei_then_haruka():
    assert DEFAULT_VOICES == {
        "en": ("Zira",),
        "ja": ("Yukkuri Reimu", "Yukkuri", "Mei", "Haruka"),
    }


def test_pick_english_default_is_zira():
    assert pick_voice("tests passed", AVAIL) == ZIRA


def test_pick_japanese_text_gets_reimu_even_when_listed_after_marisa_and_mei():
    assert pick_voice("テスト完了", AVAIL) == YUKKURI
    assert pick_voice("テスト完了", [MARISA, MEI, YUKKURI]) == YUKKURI


def test_pick_japanese_falls_back_to_mei_then_haruka():
    assert pick_voice("テスト完了", AVAIL[:5]) == MEI
    assert pick_voice("テスト完了", AVAIL[:4]) == HARUKA


def test_pick_never_chooses_a_chinese_voice_by_default():
    # Chinese is stripped before this is reached, but even raw ideographs
    # must not route to Huihui
    assert pick_voice("测试通过", AVAIL) == ZIRA


def test_pick_preferred_substring_case_insensitive():
    assert pick_voice("hello", AVAIL, preferred="david") == DAVID


def test_pick_preferred_missing_falls_back_to_language_default():
    assert pick_voice("hello", AVAIL, preferred="Aria") == ZIRA


def test_pick_language_default_missing_falls_back_to_first_available():
    assert pick_voice("テスト", [DAVID]) == DAVID


def test_pick_no_voices_raises():
    with pytest.raises(ValueError):
        pick_voice("hello", [])


def test_pick_prefers_an_exact_preset_name_over_a_substring_hit():
    # "AquesTalk10 F1" is also a substring of the earlier デフォルト entry's type "F1E"
    voices = [
        "デフォルト (AquesTalkPlayer AquesTalk10 F1E)",
        "AquesTalk10 F1 (AquesTalkPlayer AquesTalk10 F1E)",
        "AquesTalk10 F2 (AquesTalkPlayer AquesTalk10 F2E)",
    ]
    assert pick_voice("テスト", voices, preferred="AquesTalk10 F1") == voices[1]
    assert pick_voice("テスト", voices, preferred="aquestalk10 f2") == voices[2]
    assert pick_voice("テスト", voices, preferred="F1E") == voices[0]  # plain substring still works
