import re

import pytest
from conftest import AVAIL, HARUKA, MARISA, YUKKURI, ZIRA
from mcp.shared.memory import create_connected_server_and_client_session as client_session

from claude_talk.server import build_server, default_voice_from_env, project_label_from_env, quiet_import


async def _call(speaker, args, tool="speak", **server):
    """Build the server, call one tool over an in-memory MCP session, let the speech finish."""
    async with client_session(build_server(speaker, **server)._mcp_server) as client:
        res = await client.call_tool(tool, args)
    assert speaker.wait_idle(5)
    return res


def _text(result):
    assert result.content, result
    return result.content[0].text


class FakeKana:
    """Stands in for kana.transliterate: every Latin word becomes カナ."""

    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return re.sub(r"[A-Za-z']+", "カナ", text).replace(".", "。")


class FakeNotation:
    """Stands in for notation.to_notation: pure-ASCII text -> a fixed notation."""

    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return "#>えぬ'。" if text.isascii() else None


# ------------------------------------------------------------------ tools
@pytest.mark.anyio
async def test_tools_exposed(speaker):
    server = build_server(speaker, project_label="Claude Talk")
    async with client_session(server._mcp_server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools.tools}
    assert names == {"speak", "stop_speaking", "list_voices"}
    speak = next(t for t in tools.tools if t.name == "speak")
    assert set(speak.inputSchema["properties"]) >= {
        "text",
        "voice",
        "rate",
        "interrupt",
        "announce_project",
        "katakana",
    }
    assert speak.inputSchema["required"] == ["text"]
    # the description is what tells Claude WHEN to use it
    assert "short" in speak.description.lower()


# ------------------------------------------------------- without katakana
@pytest.mark.anyio
async def test_speak_prefixes_project_label_and_reports_voice(backend, speaker):
    res = await _call(speaker, {"text": "**tests** passed"}, project_label="Claude Talk")
    assert res.isError is False
    assert backend.calls == [("Claude Talk. tests passed.", ZIRA, 0, 100)]
    out = _text(res)
    assert "Zira" in out
    assert "tests passed" in out


@pytest.mark.anyio
async def test_japanese_body_goes_to_yukkuri_while_label_stays_english(backend, speaker):
    res = await _call(speaker, {"text": "テストが終わりました"}, project_label="Claude Talk")
    assert res.isError is False
    assert backend.calls == [("Claude Talk.", ZIRA, 0, 100), ("テストが終わりました。", YUKKURI, 0, 100)]
    assert "Yukkuri" in _text(res)


@pytest.mark.anyio
async def test_speak_can_skip_project_prefix(backend, speaker):
    await _call(speaker, {"text": "tests passed", "announce_project": False}, project_label="Claude Talk")
    assert backend.calls[0][0] == "tests passed."


@pytest.mark.anyio
async def test_speak_without_label_has_no_prefix(backend, speaker):
    await _call(speaker, {"text": "hi"})
    assert backend.calls[0][0] == "hi."


@pytest.mark.anyio
async def test_speak_passes_voice_rate_and_interrupt(backend, speaker):
    res = await _call(speaker, {"text": "hey", "voice": "david", "rate": 3, "interrupt": True})
    assert res.isError is False
    assert backend.calls[0][1:] == (AVAIL[0], 3, 100)


@pytest.mark.anyio
async def test_speak_empty_text_is_a_tool_error(speaker):
    assert (await _call(speaker, {"text": "   "})).isError is True


@pytest.mark.anyio
async def test_speak_reports_truncation(speaker):
    res = await _call(speaker, {"text": "Long sentence here. " * 50}, max_chars=40)
    assert "truncated" in _text(res).lower()


@pytest.mark.anyio
async def test_stop_speaking_tool(speaker):
    res = await _call(speaker, {}, tool="stop_speaking")
    assert res.isError is False
    assert "0" in _text(res)


@pytest.mark.anyio
async def test_list_voices_tool(speaker):
    res = await _call(speaker, {}, tool="list_voices")
    joined = " ".join(c.text for c in res.content)
    for v in AVAIL:
        assert v in joined


# ---------------------------------------------------------- with katakana
@pytest.mark.anyio
async def test_english_is_transliterated_and_whole_utterance_is_yukkuri(backend, speaker):
    kana = FakeKana()
    res = await _call(speaker, {"text": "**All tests** passed."}, project_label="Claude Talk", kana=kana)
    assert res.isError is False
    assert kana.calls == ["All tests passed.", "Claude Talk"]  # markdown stripped first
    # label and body share the yukkuri voice, so they merge into one engine call
    assert backend.calls == [("カナ カナ。 カナ カナ カナ。", YUKKURI, 0, 100)]
    out = _text(res)
    assert "Yukkuri" in out and "All tests passed." in out and "カナ カナ カナ" in out


@pytest.mark.anyio
async def test_explicit_english_voice_skips_katakana(backend, speaker):
    kana = FakeKana()
    await _call(speaker, {"text": "hello there", "voice": "zira"}, project_label="Claude Talk", kana=kana)
    assert kana.calls == []
    assert backend.calls == [("Claude Talk. hello there.", ZIRA, 0, 100)]


@pytest.mark.anyio
async def test_katakana_false_keeps_english_on_zira(backend, speaker):
    kana = FakeKana()
    await _call(speaker, {"text": "hello again", "katakana": False}, kana=kana)
    assert kana.calls == []
    assert backend.calls[0][:2] == ("hello again.", ZIRA)


@pytest.mark.anyio
async def test_japanese_body_with_a_latin_word_is_converted(backend, speaker):
    kana = FakeKana()
    await _call(speaker, {"text": "テストが passed"}, kana=kana)
    assert kana.calls == ["テストが passed。"]
    assert backend.calls[0][:2] == ("テストが カナ。", YUKKURI)


@pytest.mark.anyio
async def test_pure_japanese_body_only_converts_the_label(backend, speaker):
    kana = FakeKana()
    await _call(speaker, {"text": "ビルド成功"}, project_label="Claude Talk", kana=kana)
    assert kana.calls == ["Claude Talk"]
    assert backend.calls == [("カナ カナ。 ビルド成功。", YUKKURI, 0, 100)]


@pytest.mark.anyio
async def test_label_voice_override_keeps_label_on_that_voice(backend, speaker):
    await _call(speaker, {"text": "done"}, project_label="Claude Talk", kana=FakeKana(), label_voice="zira")
    assert backend.calls == [("カナ カナ。", ZIRA, 0, 100), ("カナ。", YUKKURI, 0, 100)]


# ------------------------------------------- accent notation (AquesTalk)
@pytest.mark.anyio
async def test_english_for_an_aquestalk_voice_is_sent_as_notation(backend, speaker):
    notation = FakeNotation()
    res = await _call(speaker, {"text": "**All tests** passed."}, kana=FakeKana(), notation=notation)
    assert notation.calls == ["All tests passed."]  # the English, not the katakana
    assert backend.calls == [("#>えぬ'。", YUKKURI, 0, 100)]
    out = _text(res)
    assert "カナ カナ カナ。" in out and "All tests passed." in out  # the reply stays readable
    assert "#>" not in out


@pytest.mark.anyio
async def test_label_is_notation_too_and_merges_with_the_body(backend, speaker):
    await _call(speaker, {"text": "done"}, project_label="Claude Talk", kana=FakeKana(), notation=FakeNotation())
    assert backend.calls == [("#>えぬ'。 #>えぬ'。", YUKKURI, 0, 100)]  # the backend splits the lines


@pytest.mark.anyio
async def test_mixed_japanese_falls_back_to_katakana(backend, speaker):
    notation = FakeNotation()
    await _call(speaker, {"text": "テストが passed"}, kana=FakeKana(), notation=notation)
    assert notation.calls == ["テストが passed。"]
    assert backend.calls[0][:2] == ("テストが カナ。", YUKKURI)


@pytest.mark.anyio
async def test_windows_japanese_voice_never_gets_notation(backend, speaker):
    notation = FakeNotation()
    await _call(speaker, {"text": "done", "voice": "haruka"}, kana=FakeKana(), notation=notation)
    assert notation.calls == []
    assert backend.calls == [("カナ。", HARUKA, 0, 100)]


# ------------------------------------------------------- project label
@pytest.mark.parametrize(
    "env,cwd,label",
    [
        ({}, "D:/2files/tools/Claude_Talk", "Claude Talk"),  # folder name, separators as spaces
        ({}, "D:\\2files\\fina\\auto-quant\\", "auto quant"),
        ({"CLAUDE_TALK_PROJECT": "Quant"}, "D:/x", "Quant"),  # the env var overrides
        ({"CLAUDE_TALK_PROJECT": "off"}, "D:/x", None),  # or turns it off
        ({"CLAUDE_TALK_PROJECT": ""}, "D:/x", None),
    ],
)
def test_project_label(env, cwd, label):
    assert project_label_from_env(env, cwd) == label


# ---------------------------------------------------------- quiet import
def test_quiet_import_moves_import_time_prints_to_stderr(tmp_path, monkeypatch, capsys):
    # pyopenjtalk-plus prints an ONNX warning to STDOUT on import; stdout is
    # the MCP protocol channel, so that line must end up on stderr instead.
    (tmp_path / "noisy_engine_mod.py").write_text("print('Warning: engine says hi')\nVALUE = 42\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = quiet_import("noisy_engine_mod")
    assert mod is not None and mod.VALUE == 42
    out, err = capsys.readouterr()
    assert out == ""
    assert "engine says hi" in err


def test_quiet_import_returns_none_for_missing_module(capsys):
    assert quiet_import("definitely_not_a_module_xyz") is None
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------- default voice
@pytest.mark.anyio
async def test_default_voice_applies_to_body_and_label(backend, speaker):
    res = await _call(speaker, {"text": "done"}, project_label="Claude Talk", kana=FakeKana(), default_voice="marisa")
    assert backend.calls == [("カナ カナ。 カナ。", MARISA, 0, 100)]
    assert "Marisa" in _text(res)


@pytest.mark.anyio
async def test_default_english_voice_disables_katakana(backend, speaker):
    kana = FakeKana()
    await _call(speaker, {"text": "hello there"}, project_label="Claude Talk", kana=kana, default_voice="zira")
    assert kana.calls == []
    assert backend.calls == [("Claude Talk. hello there.", ZIRA, 0, 100)]


@pytest.mark.anyio
async def test_explicit_voice_beats_the_default(backend, speaker):
    await _call(speaker, {"text": "done", "voice": "reimu"}, kana=FakeKana(), default_voice="marisa")
    assert backend.calls[0][1] == YUKKURI


def test_default_voice_env_beats_file_beats_nothing(tmp_path):
    assert default_voice_from_env({}, str(tmp_path)) is None
    (tmp_path / "voice.txt").write_text("# pick one\n\n  まりさ  \n", encoding="utf-8")
    assert default_voice_from_env({}, str(tmp_path)) == "まりさ"
    assert default_voice_from_env({"CLAUDE_TALK_VOICE": "zira"}, str(tmp_path)) == "zira"
    assert default_voice_from_env({"CLAUDE_TALK_VOICE": "  "}, str(tmp_path)) == "まりさ"
