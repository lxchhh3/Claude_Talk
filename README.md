# Claude Talk

An MCP server that lets Claude Code read short messages aloud in a yukkuri
(ゆっくり) voice, so you hear "done" or "I need your input" even when the
terminal is buried or you are on your phone.

## Tools

| tool | what it does |
| --- | --- |
| `speak(text, voice?, rate?, interrupt?, announce_project?, katakana?)` | Queue a short message. Markdown, code blocks and URLs are stripped; the project folder name is spoken first so you know which session is talking. |
| `stop_speaking()` | Cut off the current utterance and drop anything queued. |
| `list_voices()` | The voices available: the yukkuri presets plus the Windows SAPI voices. |

## Voice

- **Yukkuri Reimu** (default) and **Yukkuri Marisa**: the real AquesTalk voices,
  rendered by AQUEST's free-for-personal-use **AquesTalkPlayer** through its
  command line (`AquesTalkPlayer.exe /T text /P れいむ /W out.wav`, about 0.2 s
  per sentence) and played by the server. The player sits under the project
  root (`aquestalkplayer_*/aquestalkplayer/`, or `CLAUDE_TALK_AQTK_EXE`); its
  presets file defines the voices. It reads kanji itself.
- **English becomes Japanese-accented English**: Latin words are transliterated
  to katakana before speaking ("All tests passed" → オール テスツ パスト). Per
  word: a small override table for project jargon (`claude_talk/kana.py`), then
  the standard loanword spelling from JMdict (センテンス, レビュー, コンピューター;
  ~8,000 words in `claude_talk/data/loanwords.tsv`, plus their -s/-ed/-ing
  forms; words the rules already read the same way are left out of the file), then the CMU pronouncing dictionary with ARPAbet→kana rules, letter
  names for acronyms, and a romaji-style reading for unknown words. The rules
  take unstressed endings from the spelling the way loanwords do (-ted →
  テッド, -et → ェット, -age → ェージ, -tion → ション, -en → ズン/クン/デン,
  -le → ル, -are/-ear/-ore → ア, ar + consonant → アー).
- **English stress**: for AquesTalkPlayer voices, all-English text is sent as
  AQUEST's phonetic notation (`#>ちぇ'っく/ざろ'ぐ。`), with each content word
  accented where English stresses it (comPUter → コンピュ'ーター) and little
  words leaning on their neighbour ("the log" → ざろ'ぐ). Text with Japanese in
  it uses the normal reader; if the player ever rejects the notation the line
  is retried as plain katakana. The reply shows the katakana that was spoken.
  `katakana=False` or an English `voice` (e.g. `"zira"`) speaks English as is.
- **Chinese is never spoken**: ideographs with no kana anywhere in the message
  are treated as Chinese and removed before speaking. Korean is removed too.
- **Fallbacks**: Windows Haruka for Japanese if the player is missing; Open
  JTalk's Mei (`CLAUDE_TALK_MEI=1`, pitched up) is kept but off by default.

## Picking a voice: the `voice` command

Every preset in the player's `AquesTalkPlayer.preset` is exposed as a voice
(れいむ, まりさ, 女性３, ロボット, 機械, the AquesTalk2 and AquesTalk10 presets, ...),
plus the Windows SAPI voices. **Double-click `voice.cmd`** for an interactive
picker that stays open: type a number or name to hear a voice, `set N` to make
it the default, `say some text` to test a line (`plain some text` = the same
without English stress, to compare), `q` to quit. From a terminal in
the project folder the same file takes one-shot commands:

```
voice                    interactive picker (same as double-click)
voice list               numbered list, * marks the current default
voice list aquestalk1    filtered list
voice play               play a sample in every voice, each saying its name
voice play 2 f3 zira     only those (number or substring)
voice set まりさ          make it the default: writes voice.txt and confirms aloud
voice show               what the default is and which voice it resolves to
voice say All tests passed.   speak a line (English read as katakana) in the default voice
voice say --plain All tests passed.   the same without English stress
```

`set` writes the preset name into `voice.txt`; `CLAUDE_TALK_VOICE` in the MCP
registration overrides the file. Nothing set means Yukkuri Reimu. Restart
Claude Code sessions after changing it; per message, `voice="marisa"` still
overrides. Add your own presets in the player's GUI (they land in the same
file) and they show up after a restart.

Utterances from different Claude Code sessions are serialised through a
per-session named mutex (`Local\ClaudeTalkSpeak`), so two terminals finishing
at the same time take turns instead of talking over each other.

## Layout

```
run_server.py            launcher Claude Code runs (stdio MCP)
claude_talk/text.py      markdown -> speech text, truncation, voice choice (pure)
claude_talk/kana.py      English -> katakana transliteration + stress position (cmudict + rules)
claude_talk/loanwords.py JMdict loanword spellings: builder + loader for data/loanwords.tsv
claude_talk/notation.py  English -> accent-marked AquesTalk notation (#>...)
claude_talk/speaker.py   worker thread + queue, CompositeBackend, SapiBackend, mutex
claude_talk/aquestalk.py AquesTalkPlayer command-line backend (the yukkuri voice)
claude_talk/audio.py     numpy-free WAV helpers + winsound player
claude_talk/jtalk.py     optional Open JTalk (Mei) backend
claude_talk/server.py    FastMCP tools, project label, main()
claude_talk/cli.py       the `voice` command (list / play / set / show / say)
voice.cmd                launcher for it (python -m claude_talk.cli); voice.txt holds the chosen default
scripts/smoke_client.py  spawns the server over stdio and makes it talk
scripts/build_loanwords.py  rebuilds data/loanwords.tsv from JMdict_e.gz
tests/                   unit tests (fake engines) + opt-in audio tests
```

## Registration

Registered at user scope (all projects) with:

```
claude mcp add --scope user claude-talk -e PYTHONUTF8=1 -- D:/2files/env_build/conda/conda/python.exe -u D:/2files/tools/Claude_Talk/run_server.py
```

Restart Claude Code sessions to pick up changes. Environment knobs:

| variable | effect |
| --- | --- |
| `CLAUDE_TALK_PROJECT` | spoken prefix; `off` disables, default = cwd folder name |
| `CLAUDE_TALK_VOICE` | default voice (substring of a voice name); `voice.txt` is the file equivalent |
| `CLAUDE_TALK_KATAKANA` | `0` disables the English→katakana step (English then goes to Zira) |
| `CLAUDE_TALK_ACCENT` | `0` turns off the English-stress notation (plain katakana to AquesTalk) |
| `CLAUDE_TALK_AQTK_EXE` | path to AquesTalkPlayer.exe (default: found under the project root) |
| `CLAUDE_TALK_LABEL_VOICE` | force a voice for the prefix (default: same routing as the body) |
| `CLAUDE_TALK_MEI` | `1` adds the Open JTalk fallback voice (`CLAUDE_TALK_PITCH`, `CLAUDE_TALK_SPEED`) |
| `CLAUDE_TALK_MAX_CHARS` | truncation limit (default 800) |
| `CLAUDE_TALK_LOG` | log level on stderr (default INFO) |

## Dependencies

Base conda Python (`D:/2files/env_build/conda/conda/python.exe`, 3.13) with
`mcp` and `pywin32` (already present) plus `cmudict` (pronunciations, 1 MB).
Optional, only for `CLAUDE_TALK_MEI=1`: `pyopenjtalk-plus`, `sudachipy`,
`sudachidict_core`. The server process never imports numpy: conda's MKL numpy
loads two OpenMP runtimes, which is what broke an earlier translator attempt
(lesson #314). AquesTalkPlayer is AQUEST's own download (Cloudflare-gated,
fetch it in a browser) and free for personal, non-commercial use. Claude Talk
only drives its documented command line; it does not load the AquesTalk DLLs
(that needs AQUEST's developer licence).

`claude_talk/data/loanwords.tsv` is derived from JMdict (© EDRDG, CC BY-SA 4.0,
https://www.edrdg.org/edrdg/licence.html); the file says so in its header and
stays under that licence. Rebuild it with
`python -I -X utf8 scripts/build_loanwords.py JMdict_e.gz`
(download: http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz).

## Tests

```
cd D:/2files/tools/Claude_Talk
PYTHONUTF8=1 PYTHONPATH=. python -m pytest                      # silent, fake engines
CLAUDE_TALK_AUDIO=1 PYTHONUTF8=1 PYTHONPATH=. python -m pytest tests/test_integration_sapi.py tests/test_integration_aquestalk.py
CLAUDE_TALK_AUDIO=1 PYTHONUTF8=1 PYTHONPATH=. python -m pytest tests/test_integration_jtalk.py   # Mei, alone
python scripts/smoke_client.py "All tests passed."             # full stdio round trip
```
