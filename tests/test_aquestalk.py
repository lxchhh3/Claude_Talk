"""AquesTalkPlayer backend with the command line and the audio player faked."""
import io
import os
import threading
import time
import wave

import numpy as np
import pytest

from claude_talk.aquestalk import (
    MARISA_VOICE,
    REIMU_VOICE,
    AquesTalkPlayerBackend,
    safe_text,
)

EXE = "C:/x/AquesTalkPlayer.exe"


class FakeRunner:
    """Stands in for running AquesTalkPlayer.exe: records the argv and writes
    the WAV the real player would write at the /W path."""

    def __init__(self, rc=0, seconds=0.5, sr=16000, write=True):
        self.calls = []
        self.rc = list(rc) if isinstance(rc, (list, tuple)) else rc  # a list = one code per call
        self.seconds = seconds
        self.sr = sr
        self.write = write

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        rc = self.rc.pop(0) if isinstance(self.rc, list) else self.rc
        if self.write and rc == 0:
            out = args[args.index("/W") + 1]
            with wave.open(out, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.sr)
                w.writeframes(np.full(int(self.sr * self.seconds), 1000, "<i2").tobytes())
        return rc


class FakePlayer:
    def __init__(self):
        self.played = []
        self.purged = 0

    def play(self, wav, duration, stop):
        self.played.append((wav, duration))
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if stop.wait(0.01):
                self.purged += 1
                return


def _parse(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


@pytest.fixture
def parts():
    runner, player = FakeRunner(), FakePlayer()
    return runner, player, AquesTalkPlayerBackend(EXE, runner=runner, player=player)


def test_voices_are_the_presets_reimu_first(parts):
    _, _, backend = parts
    assert backend.voices() == [REIMU_VOICE, MARISA_VOICE]
    assert REIMU_VOICE == "Yukkuri Reimu (AquesTalkPlayer れいむ)"
    assert MARISA_VOICE == "Yukkuri Marisa (AquesTalkPlayer まりさ)"


def test_speak_runs_the_cli_with_the_preset_and_plays_the_wav(parts):
    runner, player, backend = parts
    backend.speak("テスト完了。", REIMU_VOICE, 0, 100)
    args = runner.calls[0]
    assert args[0] == EXE
    assert args[1:5] == ["/T", "テスト完了。", "/P", "れいむ"]
    assert args[5] == "/W" and args[6].lower().endswith(".wav")
    assert not os.path.exists(args[6]), "temp wav should be removed after playback"
    wav, duration = player.played[0]
    sr, samples = _parse(wav)
    assert sr == 16000 and len(samples) == 8000
    assert duration == pytest.approx(0.5, abs=0.01)
    assert samples[0] == 1000


def test_marisa_voice_selects_its_preset(parts):
    runner, _, backend = parts
    backend.speak("x", MARISA_VOICE, 0, 100)
    assert runner.calls[0][4] == "まりさ"


def test_unknown_voice_raises(parts):
    _, _, backend = parts
    with pytest.raises(ValueError):
        backend.speak("x", "Microsoft Zira", 0, 100)


def test_volume_scales_samples(parts):
    _, player, backend = parts
    backend.speak("x", REIMU_VOICE, 0, 50)
    _, samples = _parse(player.played[0][0])
    assert samples[0] == 500


def test_text_is_quote_free_and_cp932_safe():
    assert safe_text('say "hi" 🎉 テスト') == "say hi テスト"
    assert safe_text("a\nb") == "a b"


def test_notation_reaches_the_player_unchanged(parts):
    runner, _, backend = parts
    backend.speak("#>ちぇ'っく/ざろ'ぐ。", REIMU_VOICE, 0, 100)
    assert runner.calls[0][2] == "#>ちぇ'っく/ざろ'ぐ。"


@pytest.mark.parametrize(
    "merged,lines",
    [
        # label and body merged by the speaker: each notation part gets its own line
        ("#>くろ'ーど。 #>だ'ん。", "#>くろ'ーど。\r\n#>だ'ん。"),
        ("#>くろ'ーど。 ビルド成功。", "#>くろ'ーど。\r\nビルド成功。"),
        ("ラベル。 #>だ'ん。", "ラベル。\r\n#>だ'ん。"),
        ("ビルド 成功。", "ビルド 成功。"),  # plain text stays one line
    ],
)
def test_notation_and_plain_parts_go_on_separate_lines(parts, merged, lines):
    runner, _, backend = parts
    backend.speak(merged, REIMU_VOICE, 0, 100)
    assert runner.calls[0][2] == lines


def test_rejected_notation_is_retried_as_plain_text():
    runner, player = FakeRunner(rc=[2008, 0]), FakePlayer()
    backend = AquesTalkPlayerBackend(EXE, runner=runner, player=player)
    backend.speak("#>ちぇ'っく/ざろ'ぐ。", REIMU_VOICE, 0, 100)
    assert [c[2] for c in runner.calls] == ["#>ちぇ'っく/ざろ'ぐ。", "チェック ザログ。"]
    assert len(player.played) == 1


def test_notation_rejected_twice_raises():
    backend = AquesTalkPlayerBackend(EXE, runner=FakeRunner(rc=[2008, 2008]), player=FakePlayer())
    with pytest.raises(RuntimeError, match="2008"):
        backend.speak("#>ちぇ'っく。", REIMU_VOICE, 0, 100)


def test_cli_failure_raises_with_the_players_code():
    runner = FakeRunner(rc=2021, write=False)
    backend = AquesTalkPlayerBackend(EXE, runner=runner, player=FakePlayer())
    with pytest.raises(RuntimeError, match="2021"):
        backend.speak("x", REIMU_VOICE, 0, 100)


def test_missing_output_raises():
    backend = AquesTalkPlayerBackend(EXE, runner=FakeRunner(write=False), player=FakePlayer())
    with pytest.raises(RuntimeError):
        backend.speak("x", REIMU_VOICE, 0, 100)


def test_stop_cuts_playback_short():
    runner, player = FakeRunner(seconds=5.0), FakePlayer()
    backend = AquesTalkPlayerBackend(EXE, runner=runner, player=player)
    t = threading.Thread(target=backend.speak, args=("long", REIMU_VOICE, 0, 100))
    t0 = time.monotonic()
    t.start()
    while not player.played and time.monotonic() - t0 < 2:
        time.sleep(0.01)
    backend.stop()
    t.join(2)
    assert not t.is_alive()
    assert player.purged == 1


def test_default_runner_requires_an_existing_exe(tmp_path):
    with pytest.raises(FileNotFoundError):
        AquesTalkPlayerBackend(str(tmp_path / "nope.exe"))


def test_find_aquestalk_exe_searches_two_levels_down(tmp_path):
    from claude_talk.aquestalk import find_aquestalk_exe

    assert find_aquestalk_exe(str(tmp_path)) is None
    exe = tmp_path / "aquestalkplayer_20250606" / "aquestalkplayer" / "AquesTalkPlayer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert find_aquestalk_exe(str(tmp_path)) == str(exe)


# ---------------------------------------------------------- preset file
PRESET_CSV = (
    "プリセット名,棒読み,エンジン,声種,話速,音量,高さ,アクセント,声質,音程,メモ\n"
    '"デフォルト","false","AquesTalk10","F1E",100,100,100,100,100,100,"AquesTalk10 女声"\n'
    '"れいむ","true","AquesTalk1","f1",100,100,100,100,100,100,"ゆっくり霊夢"\n'
    '"まりさ","true","AquesTalk1","f2",100,100,100,100,100,100,"ゆっくり魔理沙"\n'
    '"女性３","false","AquesTalk1","f3",100,100,100,100,100,100,""\n'
    '"ロボット","false","AquesTalk1","m2",100,100,100,100,100,100,""\n'
)


def _write_presets(tmp_path):
    exe = tmp_path / "AquesTalkPlayer.exe"
    exe.write_bytes(b"")
    (tmp_path / "AquesTalkPlayer.preset").write_bytes(PRESET_CSV.encode("cp932"))
    return str(exe)


def test_presets_are_read_from_the_players_cp932_file(tmp_path):
    from claude_talk.aquestalk import load_presets

    exe = _write_presets(tmp_path)
    presets = load_presets(exe)
    assert list(presets) == ["デフォルト", "れいむ", "まりさ", "女性３", "ロボット"]
    assert presets["デフォルト"] == ("AquesTalk10", "F1E")
    assert presets["女性３"] == ("AquesTalk1", "f3")


def test_all_presets_become_voices_with_reimu_and_marisa_first(tmp_path):
    exe = _write_presets(tmp_path)
    backend = AquesTalkPlayerBackend(exe, runner=FakeRunner(), player=FakePlayer())
    assert backend.voices()[:2] == [REIMU_VOICE, MARISA_VOICE]
    assert "デフォルト (AquesTalkPlayer AquesTalk10 F1E)" in backend.voices()
    assert "女性３ (AquesTalkPlayer AquesTalk1 f3)" in backend.voices()
    assert len(backend.voices()) == 5


def test_any_preset_voice_selects_its_preset(tmp_path):
    exe = _write_presets(tmp_path)
    runner = FakeRunner()
    backend = AquesTalkPlayerBackend(exe, runner=runner, player=FakePlayer())
    backend.speak("x", "女性３ (AquesTalkPlayer AquesTalk1 f3)", 0, 100)
    assert runner.calls[0][4] == "女性３"


def test_missing_preset_file_falls_back_to_reimu_and_marisa():
    backend = AquesTalkPlayerBackend(EXE, runner=FakeRunner(), player=FakePlayer())
    assert backend.voices() == [REIMU_VOICE, MARISA_VOICE]
