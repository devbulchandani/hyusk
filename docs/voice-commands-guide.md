# Voice Commands Guide

This guide explains how to use voice commands with Hyusk.

## Quick Start

### 1. Enable Voice in Configuration

Edit your `.env` file and set:

```bash
VOICE_ENABLED=true
```

### 2. Run Voice Mode

```bash
python -m hyusk voice
```

Or without wake word detection (start listening immediately):

```bash
python -m hyusk voice --no-wake-word
```

## How It Works

### With Wake Word (Default)

1. Start voice mode: `python -m hyusk voice`
2. Wait for the system to initialize (loads Whisper model for speech recognition)
3. Say the wake word: **"hey hyusk"** (or your custom wake word)
4. Speak your command within 3 seconds
5. Hyusk transcribes, processes, and responds with voice

### Without Wake Word

1. Start: `python -m hyusk voice --no-wake-word`
2. System starts listening immediately
3. Speak your command (3 seconds)
4. Hyusk responds
5. Repeat for each command

## Configuration Options

In your `.env` file:

```bash
# Enable/disable voice features
VOICE_ENABLED=true

# Wake word phrase (what you say to activate)
WAKE_WORD=hey hyusk

# Speech-to-Text Settings
STT_PROVIDER=whisper          # Speech recognition engine
STT_MODEL=base                # Model size: tiny, base, small, medium, large
STT_LANGUAGE=en               # Language code

# Text-to-Speech Settings
TTS_PROVIDER=kokoro           # TTS engine (kokoro or system)
TTS_VOICE=default             # Voice to use
TTS_SPEED=1.0                 # Speech speed (0.5-2.0)
```

### Choosing STT Model Size

| Model  | Size  | Speed     | Accuracy | Use Case                    |
|--------|-------|-----------|----------|-----------------------------|
| tiny   | 75MB  | Fastest   | Good     | Quick testing               |
| base   | 142MB | Fast      | Better   | **Recommended for most**    |
| small  | 466MB | Moderate  | Good     | Better accuracy needed      |
| medium | 1.5GB | Slow      | Better   | High accuracy required      |
| large  | 2.9GB | Slowest   | Best     | Maximum accuracy            |

**Recommendation**: Start with `base` - it's a good balance of speed and accuracy.

## Installation Requirements

### Required Dependencies

Voice mode requires additional Python packages:

```bash
# Speech recognition (Whisper)
pip install openai-whisper

# Audio processing
pip install pyaudio sounddevice numpy

# Text-to-speech (optional, uses system TTS by default)
pip install kokoro-tts  # If using Kokoro TTS
```

### macOS Audio Permissions

On macOS, you may need to grant microphone permissions:

1. System Settings → Privacy & Security → Microphone
2. Enable access for Terminal or your Python app

## Example Commands

Once in voice mode, you can say:

- **"Open Brave browser"** - Opens applications
- **"Play music on Spotify"** - Controls apps
- **"What's the weather like?"** - Get information
- **"Create a file called notes.txt"** - File operations
- **"Run the tests"** - Execute commands
- **"Exit"** / **"Quit"** / **"Goodbye"** - Stop voice mode

## Command Options

```bash
# Basic voice mode with wake word
python -m hyusk voice

# Skip wake word detection
python -m hyusk voice --no-wake-word

# Use a specific LLM model
python -m hyusk voice --model openai

# Combine options
python -m hyusk voice --no-wake-word --model openai
```

## Troubleshooting

### "No module named 'whisper'"

Install OpenAI Whisper:
```bash
pip install openai-whisper
```

### "No module named 'pyaudio'"

Install audio dependencies:
```bash
# macOS
brew install portaudio
pip install pyaudio

# Linux
sudo apt-get install portaudio19-dev
pip install pyaudio
```

### Wake Word Not Detecting

The default wake word detector uses Whisper (resource-intensive). Consider:

1. Use `--no-wake-word` flag to skip wake word detection
2. Speak clearly and at normal volume
3. Reduce background noise
4. Try a different wake word in `.env`

### Voice Response Not Playing

The default TTS uses system text-to-speech:

- **macOS**: Uses built-in `say` command (should work automatically)
- **Linux**: Install `espeak` or `festival`
- **Windows**: Uses built-in SAPI

### Whisper Model Download Slow

First run downloads the model (142MB for base). This happens once:

```bash
# Pre-download models
python -c "import whisper; whisper.load_model('base')"
```

### "No speech detected"

- Speak louder or closer to the microphone
- Check microphone permissions
- Verify microphone is working: `python -m sounddevice`
- Increase recording duration by editing the code

## Advanced: Porcupine Wake Word

For better wake word detection (lower CPU usage), use Picovoice Porcupine:

1. Get a free access key from https://console.picovoice.ai/
2. Install: `pip install pvporcupine`
3. Add to `.env`:
   ```bash
   PORCUPINE_ACCESS_KEY=your_key_here
   ```

Note: The current implementation uses `SimpleWakeWord` (Whisper-based). To use Porcupine, you'd need to update the CLI code to use `PorcupineWakeWord`.

## Tips for Best Results

1. **Speak clearly** - Enunciate words, avoid mumbling
2. **Reduce background noise** - Close windows, turn off fans
3. **Use a good microphone** - Built-in mics work, but external is better
4. **Keep commands concise** - "Open Brave" vs "Could you please open the Brave browser for me?"
5. **Wait for prompts** - Let the system finish before speaking again
6. **Start with `--no-wake-word`** - Easier for testing and continuous use

## Example Session

```bash
$ python -m hyusk voice --no-wake-word

╭───────────────────╮
│ Hyusk Voice Mode  │
╰───────────────────╯
Press Ctrl+C to exit

Initializing voice components...
✓ Voice components ready

Listening... (3 seconds)
Transcribing...
You: Open Brave browser

Thinking...
Hyusk: Opening Brave Browser now.
Speaking...

Listening... (3 seconds)
Transcribing...
You: Play music on Spotify

Thinking...
Hyusk: Opening Spotify.
Speaking...

Listening... (3 seconds)
Transcribing...
You: Exit

Goodbye!
```

## What's Next?

- Check `docs/HYUSK_SPEC.md` for full feature documentation
- See available tools: `python -m hyusk doctor`
- Configure permissions: Edit `.env` file
- Run in daemon mode for always-on voice: `python -m hyusk daemon start`
