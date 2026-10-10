import pytest
from conftest import AVAIL, DAVID, HARUKA, MARISA, MEI, YUKKURI, ZIRA

from claude_talk.text import DEFAULT_VOICES, clean_text, detect_language, pick_voice, truncate


# ---------------------------------------------------------------- clean_text
@pytest.mark.parametrize(
    "raw,spoken",
    [
        ("## Done\n\n**All 12 tests** passed, see `run.log`.", "Done. All 12 tests passed, see run.log."),
        ("Fixed it:\n```python\nprint(1)\n```\nrerun now", "Fixed it: (code omitted) rerun now."),
        ("- first\n* second\n1. third", "first. second. third."),  # bullets become sentences
        ("See [the docs](https://example.com/a/b) or https://foo.bar/baz?q=1 later", "See the docs or link later."),
        ("a   b\t c!", "a b c!"),  # whitespace collapses, existing punctuation stays
        # the user does not want to hear any Chinese; no kana => Chinese. No Korean voice either.
        ("测试完成。\n请检查", ""),
        ("done 完成 now", "done now."),
        ("fullwidth：colon！bang", "fullwidth colon bang."),
        ("한국어 too", "too."),
        # kana present: Japanese stays, and ends with 。
        ("テスト完了。\n次へ", "テスト完了。 次へ。"),
        ("done テスト完了", "done テスト完了。"),
        ("完了しました。", "完了しました。"),
        ("テスト完了 ok, 한국어 too", "テスト完了 ok, too。"),
        ("- ビルド成功\n- テスト成功", "ビルド成功。 テスト成功。"),
        ("   \n```\nx\n```\n", "(code omitted)."),
        ("   \n\n", ""),
        ('He said "done."', 'He said "done."'),  # a quoted sentence is already terminated
        ("Done (see log)", "Done (see log)."),
        # Windows paths and underscored names are left alone
        ("Edited D:\\2files\\tools\\run_server.py and claude_talk.text",
         "Edited D:\\2files\\tools\\run_server.py and claude_talk.text."),
    ],
)
def test_clean_text(raw, spoken):
    assert clean_text(raw) == spoken


# ------------------------------------------------------------------ truncate
@pytest.mark.parametrize(
    "text,limit,result",
    [
        ("hi there.", 50, ("hi there.", False)),  # short text untouched
        ("First sentence. Second sentence is longer. Third one.", 30, ("First sentence.", True)),
        (("word " * 20).strip(), 23, ("word word word word", True)),  # no sentence end: a word boundary
        ("今日は完了。明日続き。", 8, ("今日は完了。", True)),
        ("x" * 50, 10, ("x" * 10, True)),  # no boundary at all: a hard cut
    ],
)
def test_truncate(text, limit, result):
    assert truncate(text, limit) == result


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


PRESETS = [
    "デフォルト (AquesTalkPlayer AquesTalk10 F1E)",
    "AquesTalk10 F1 (AquesTalkPlayer AquesTalk10 F1E)",
    "AquesTalk10 F2 (AquesTalkPlayer AquesTalk10 F2E)",
]


@pytest.mark.parametrize(
    "text,voices,preferred,voice",
    [
        ("tests passed", AVAIL, None, ZIRA),  # English default
        ("テスト完了", AVAIL, None, YUKKURI),  # Japanese: Reimu, even listed after Marisa and Mei
        ("テスト完了", [MARISA, MEI, YUKKURI], None, YUKKURI),
        ("テスト完了", AVAIL[:5], None, MEI),  # then Mei, then Haruka
        ("テスト完了", AVAIL[:4], None, HARUKA),
        # Chinese is stripped before this is reached, but raw ideographs must not route to Huihui
        ("测试通过", AVAIL, None, ZIRA),
        ("hello", AVAIL, "david", DAVID),  # a preference is a case-insensitive substring
        ("hello", AVAIL, "Aria", ZIRA),  # not installed: the language default
        ("テスト", [DAVID], None, DAVID),  # no language default installed: the first voice
        # an exact preset name beats a substring hit ("AquesTalk10 F1" is inside デフォルト's "F1E")
        ("テスト", PRESETS, "AquesTalk10 F1", PRESETS[1]),
        ("テスト", PRESETS, "aquestalk10 f2", PRESETS[2]),
        ("テスト", PRESETS, "F1E", PRESETS[0]),  # a plain substring still works
    ],
)
def test_pick_voice(text, voices, preferred, voice):
    assert pick_voice(text, voices, preferred=preferred) == voice


def test_pick_no_voices_raises():
    with pytest.raises(ValueError):
        pick_voice("hello", [])
