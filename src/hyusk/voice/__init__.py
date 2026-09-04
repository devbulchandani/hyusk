"""Voice client: bridges audio input/output to the Hyusk daemon.

The voice client is a standalone async process that connects to the
daemon via :class:`hyusk.client.client.DaemonClient` and submits user
input as ``run`` messages. Replies are rendered through a speech
renderer (markdown stripped) and played via a TTS backend.

Submodules
---------

* :mod:`hyusk.voice.tts`  — TTS backends (none, say, kokoro, openai)
* :mod:`hyusk.voice.stt`  — STT backends (text, whisper_cpp, whisper_api)
* :mod:`hyusk.voice.audio` — platform-agnostic mic/speaker abstraction
* :mod:`hyusk.voice.render` — speech renderer (markdown/code stripping)
* :mod:`hyusk.voice.client` — the main entry point (this file's sibling)
* :mod:`hyusk.voice.setup` — ``hyusk voice setup`` and ``hyusk voice doctor``

For backwards compatibility, the legacy ``stt`` and ``tts`` module
names are re-exported here.
"""

from . import audio, render, setup, stt, tts  # noqa: F401

__all__ = ["audio", "render", "setup", "stt", "tts"]
