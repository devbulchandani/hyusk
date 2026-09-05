"""Web UI for Hyusk.

A browser-based chat interface served by FastAPI. Provides a 3D
particle sphere that animates based on the agent's activity (idle,
thinking, speaking, listening, error). Uses server-sent events and
WebSockets for real-time updates.

Run with::

    hyusk webui                 # default: http://127.0.0.1:8080
    hyusk webui --port 9000     # custom port
    hyusk webui --no-share     # don't open browser

The web UI connects to the same daemon (via the WebSocket protocol)
and the same task model. It shows:

- the live 3D particle sphere (animated based on activity)
- the agent's streaming text
- the list of running tools
- a text input box for typing prompts
- (optional) a "mic" button to record from the browser's microphone
  and stream the audio to the daemon for STT

The 3D scene is rendered with three.js loaded from a CDN (jsdelivr) to
avoid bundling 600KB of JS into the package.
