#!/bin/bash
# Quick setup script for Hyusk voice commands

set -e

echo "🎤 Setting up Hyusk Voice Commands"
echo "=================================="
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated"
    echo "Run: source .venv/bin/activate"
    exit 1
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found"
    echo "Creating from .env.example..."
    cp .env.example .env
    echo "✓ Created .env file"
    echo ""
fi

# Enable voice in .env
echo "Enabling voice in configuration..."
if grep -q "^VOICE_ENABLED=" .env; then
    sed -i '' 's/^VOICE_ENABLED=.*/VOICE_ENABLED=true/' .env
else
    echo "VOICE_ENABLED=true" >> .env
fi
echo "✓ Voice enabled in .env"
echo ""

# Install required packages
echo "Installing voice dependencies..."
echo ""

echo "1/3 Installing OpenAI Whisper (speech recognition)..."
pip install -q openai-whisper

echo "2/3 Installing audio libraries..."
pip install -q sounddevice numpy soundfile

echo "3/3 Installing PyAudio..."
# Try to install pyaudio, might fail on some systems
if pip install -q pyaudio 2>/dev/null; then
    echo "✓ PyAudio installed"
else
    echo "⚠️  PyAudio installation failed"
    echo "On macOS, try: brew install portaudio && pip install pyaudio"
    echo "Voice mode will use sounddevice instead"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Quick Start:"
echo "   python -m hyusk voice --no-wake-word"
echo ""
echo "📖 Full guide: docs/voice-commands-guide.md"
echo ""
