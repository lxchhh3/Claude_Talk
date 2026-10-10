"""The `voice` command line: list / play / set / show / say, against a fake speaker."""
import io

import pytest

from claude_talk.cli import main, preset_name, resolve, sample_for

VOICES = [
    "Yukkuri Reimu (AquesTalkPlayer れいむ)",
    "Yukkuri Marisa (AquesTalkPlayer まりさ)",
    "女性３ (AquesTalkPlayer AquesTalk1 f3)",
    "Microsoft Zira Desktop - English (United States)",
]
REIMU, MARISA, F3, ZIRA = VOICES


class FakeSpeaker:
    def __init__(self):
        self.calls = []
        self.closed = False

    def voices(self):
        return list(VOICES)

    def speak(self, text, voice=None, **kw):
        self.calls.append((text, voice))

    def wait_idle(self, timeout):
        return True

    def close(self, timeout=5):
        self.closed = True


def run(argv, tmp_path, env=None, speaker=None):
    speaker = speaker or FakeSpeaker()
    out = io.StringIO()
    rc = main(argv, speaker=speaker, root=str(tmp_path), env=env or {}, out=out)
    return rc, out.getvalue(), speaker


# ----------------------------------------------------------------- helpers
def test_resolve_by_number_and_substring():
    assert resolve("2", VOICES) == MARISA
    assert resolve("f3", VOICES) == F3
    assert resolve("ZIRA", VOICES) == ZIRA


def test_resolve_errors_are_clear():
    with pytest.raises(ValueError, match="1-4"):
        resolve("9", VOICES)
    with pytest.raises(ValueError, match="nope"):
        resolve("nope", VOICES)


def test_preset_name_is_what_goes_into_voice_txt():
    assert preset_name(MARISA) == "Yukkuri Marisa"
    assert preset_name(F3) == "女性３"
    assert preset_name(ZIRA) == "Microsoft Zira Desktop - English"


def test_sample_is_katakana_for_japanese_voices_and_english_for_english_ones():
    assert sample_for(F3).startswith("女性３。")
    assert "オール テスツ パスト" in sample_for(F3)
    assert sample_for(ZIRA).startswith("Microsoft Zira Desktop - English. All tests passed")


# ---------------------------------------------------------------- commands
def test_list_numbers_voices_and_marks_the_current_default(tmp_path):
    (tmp_path / "voice.txt").write_text("まりさ\n", encoding="utf-8")
    rc, out, _ = run(["list"], tmp_path)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0].startswith("  1. Yukkuri Reimu")
    assert lines[1].startswith("* 2. Yukkuri Marisa")
    assert any(l.endswith("English (United States)") for l in lines)


def test_list_takes_a_filter(tmp_path):
    rc, out, _ = run(["list", "aquestalk1"], tmp_path)
    assert rc == 0 and "女性３" in out and "Zira" not in out


def test_play_speaks_the_sample_in_each_selected_voice(tmp_path):
    rc, out, sp = run(["play", "2", "zira"], tmp_path)
    assert rc == 0
    assert [v for _, v in sp.calls] == [MARISA, ZIRA]
    # "Yukkuri" is in the override table as ゆっくり, Marisa goes through the rules
    assert sp.calls[0][0].startswith("ゆっくり マリサ。")
    assert "Yukkuri Marisa" in out


def test_play_without_selection_plays_everything(tmp_path):
    rc, _, sp = run(["play"], tmp_path)
    assert rc == 0
    assert [v for _, v in sp.calls] == VOICES


def test_set_writes_voice_txt_and_confirms_aloud(tmp_path):
    rc, out, sp = run(["set", "3"], tmp_path)
    assert rc == 0
    text = (tmp_path / "voice.txt").read_text(encoding="utf-8")
    body = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert body == ["女性３"]
    assert sp.calls and sp.calls[-1][1] == F3
    assert "女性３" in out and "restart" in out.lower()


def test_set_quiet_does_not_speak(tmp_path):
    rc, _, sp = run(["set", "まりさ", "--quiet"], tmp_path)
    assert rc == 0 and sp.calls == []


def test_set_unknown_voice_fails_without_writing(tmp_path):
    rc, out, _ = run(["set", "nope"], tmp_path)
    assert rc == 2
    assert not (tmp_path / "voice.txt").exists()
    assert "nope" in out


def test_show_reports_default_and_resolution(tmp_path):
    rc, out, _ = run(["show"], tmp_path)
    assert rc == 0 and "(none)" in out and "Yukkuri Reimu" in out
    (tmp_path / "voice.txt").write_text("f3\n", encoding="utf-8")
    rc, out, _ = run(["show"], tmp_path)
    assert "f3" in out and "女性３" in out
    rc, out, _ = run(["show"], tmp_path, env={"CLAUDE_TALK_VOICE": "zira"})
    assert "zira" in out and "Zira" in out and "CLAUDE_TALK_VOICE" in out


def test_say_sends_accent_notation_to_aquestalk_voices(tmp_path):
    pytest.importorskip("cmudict")
    (tmp_path / "voice.txt").write_text("まりさ\n", encoding="utf-8")
    rc, out, sp = run(["say", "All", "tests", "passed."], tmp_path)
    assert rc == 0
    assert sp.calls == [("#>お'ーる/て'すつ/ぱ'すと。", MARISA)]
    assert "オール テスツ パスト。" in out and "accented" in out  # shown readable


def test_say_plain_keeps_the_katakana(tmp_path):
    (tmp_path / "voice.txt").write_text("まりさ\n", encoding="utf-8")
    rc, out, sp = run(["say", "All", "tests", "passed.", "--plain"], tmp_path)
    assert rc == 0
    assert sp.calls == [("オール テスツ パスト。", MARISA)]
    assert "accented" not in out


def test_say_with_english_voice_keeps_english(tmp_path):
    rc, _, sp = run(["say", "hello there", "--voice", "zira"], tmp_path)
    assert rc == 0
    assert sp.calls == [("hello there", ZIRA)]


def test_speaker_is_closed_after_every_command(tmp_path):
    for argv in (["list"], ["show"], ["set", "2", "--quiet"]):
        _, _, sp = run(argv, tmp_path)
        assert sp.closed


# ------------------------------------------------------------ interactive
def test_no_arguments_means_interactive_picker(tmp_path):
    pytest.importorskip("cmudict")
    lines = iter(["2", "set 3", "say hello there", "plain hello there", "nope", "q"])
    sp, out = FakeSpeaker(), io.StringIO()
    rc = main([], speaker=sp, root=str(tmp_path), env={}, out=out, inp=lambda prompt: next(lines))
    assert rc == 0
    # sample in Marisa, confirmation in 女性３ (now the default), then the test lines in it
    assert [v for _, v in sp.calls] == [MARISA, F3, F3, F3]
    assert sp.calls[2][0] == "#>はろ'ー/ぜ'あ。"  # say: English stress
    assert sp.calls[3][0] == "ハロー ゼア"  # plain: the old katakana reading, to compare
    text = (tmp_path / "voice.txt").read_text(encoding="utf-8")
    assert [l for l in text.splitlines() if l and not l.startswith("#")] == ["女性３"]
    shown = out.getvalue()
    assert "no voice matches 'nope'" in shown
    assert shown.count("1. Yukkuri Reimu") == 1  # listed once at the start
    assert "q = quit" in shown and "plain TEXT" in shown
    assert sp.closed


def test_interactive_relists_and_ends_on_eof(tmp_path):
    lines = iter(["", "l"])

    def inp(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    sp, out = FakeSpeaker(), io.StringIO()
    rc = main(["interactive"], speaker=sp, root=str(tmp_path), env={}, out=out, inp=inp)
    assert rc == 0
    assert out.getvalue().count("1. Yukkuri Reimu") == 3
    assert sp.calls == []


def test_resolve_prefers_an_exact_preset_name():
    voices = [
        "デフォルト (AquesTalkPlayer AquesTalk10 F1E)",
        "AquesTalk10 F1 (AquesTalkPlayer AquesTalk10 F1E)",
    ]
    assert resolve("AquesTalk10 F1", voices) == voices[1]
    assert resolve("f1e", voices) == voices[0]
