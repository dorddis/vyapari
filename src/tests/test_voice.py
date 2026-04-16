"""Voice service tests -- STT transcription + TTS generation.

Tests mock the OpenAI API and ffmpeg subprocess to avoid external calls.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from models import IncomingMessage, MessageType


# Override the autouse clean_state fixture -- voice tests don't need the DB
@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """No-op override: voice tests are fully mocked, no DB needed."""
    yield


# ---------------------------------------------------------------------------
# Voice message factory
# ---------------------------------------------------------------------------

def make_voice_msg(
    wa_id: str = "919876543210",
    media_url: str = "https://example.com/voice.ogg",
    media_id: str = "media_123",
) -> IncomingMessage:
    """Create a voice IncomingMessage for testing."""
    return IncomingMessage(
        wa_id=wa_id,
        text=None,
        msg_id="wamid.test_voice_001",
        msg_type=MessageType.VOICE,
        media_url=media_url,
        media_id=media_id,
        sender_name="Test Customer",
    )


# ---------------------------------------------------------------------------
# STT tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("services.voice._get_client")
@patch("services.voice._convert_ogg_to_wav")
async def test_transcribe_voice_note_ogg(mock_convert, mock_client):
    """OGG voice note is converted to WAV then transcribed."""
    from services.voice import transcribe_voice_note

    mock_convert.return_value = b"fake_wav_bytes"

    mock_transcription = MagicMock()
    mock_transcription.text = "Nexon ka price batao"
    mock_client.return_value.audio.transcriptions.create = AsyncMock(
        return_value="Nexon ka price batao"
    )

    result = await transcribe_voice_note(b"fake_ogg_bytes", "audio/ogg")

    assert result == "Nexon ka price batao"
    mock_convert.assert_called_once_with(b"fake_ogg_bytes")
    mock_client.return_value.audio.transcriptions.create.assert_called_once()


@pytest.mark.asyncio
@patch("services.voice._get_client")
async def test_transcribe_mp3_no_conversion(mock_client):
    """MP3 audio is passed directly without ffmpeg conversion."""
    from services.voice import transcribe_voice_note

    mock_client.return_value.audio.transcriptions.create = AsyncMock(
        return_value="Test drive book karo"
    )

    result = await transcribe_voice_note(b"fake_mp3_bytes", "audio/mpeg")

    assert result == "Test drive book karo"


@pytest.mark.asyncio
@patch("services.voice._get_client")
@patch("services.voice._convert_ogg_to_wav")
async def test_transcribe_failure_raises(mock_convert, mock_client):
    """Transcription failure raises RuntimeError."""
    from services.voice import transcribe_voice_note

    mock_convert.return_value = b"fake_wav_bytes"
    mock_client.return_value.audio.transcriptions.create = AsyncMock(
        side_effect=Exception("API error")
    )

    with pytest.raises(RuntimeError, match="Failed to transcribe"):
        await transcribe_voice_note(b"fake_ogg_bytes", "audio/ogg")


# ---------------------------------------------------------------------------
# TTS tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("services.voice._get_client")
async def test_generate_voice_reply(mock_client):
    """TTS generates Opus audio bytes from text."""
    from services.voice import generate_voice_reply

    mock_response = MagicMock()
    mock_response.content = b"fake_opus_audio"
    mock_client.return_value.audio.speech.create = AsyncMock(
        return_value=mock_response
    )

    result = await generate_voice_reply("Nexon XZ Plus available hai, 9.5 lakh")

    assert result == b"fake_opus_audio"
    call_kwargs = mock_client.return_value.audio.speech.create.call_args.kwargs
    assert call_kwargs["response_format"] == "opus"
    assert call_kwargs["model"] == "gpt-4o-mini-tts"


@pytest.mark.asyncio
@patch("services.voice._get_client")
async def test_generate_voice_reply_custom_instructions(mock_client):
    """TTS uses custom instructions when provided."""
    from services.voice import generate_voice_reply

    mock_response = MagicMock()
    mock_response.content = b"custom_audio"
    mock_client.return_value.audio.speech.create = AsyncMock(
        return_value=mock_response
    )

    result = await generate_voice_reply(
        "Welcome to Sharma Motors!",
        instructions="Speak formally in Hindi.",
    )

    assert result == b"custom_audio"
    call_kwargs = mock_client.return_value.audio.speech.create.call_args.kwargs
    assert call_kwargs["instructions"] == "Speak formally in Hindi."


@pytest.mark.asyncio
@patch("services.voice._get_client")
async def test_tts_failure_raises(mock_client):
    """TTS failure raises RuntimeError."""
    from services.voice import generate_voice_reply

    mock_client.return_value.audio.speech.create = AsyncMock(
        side_effect=Exception("TTS API error")
    )

    with pytest.raises(RuntimeError, match="Failed to generate voice"):
        await generate_voice_reply("test text")


# ---------------------------------------------------------------------------
# Channel adapter tests
# ---------------------------------------------------------------------------

def test_web_clone_send_audio():
    """WebCloneAdapter.send_audio enqueues base64-encoded audio."""
    import asyncio
    from channels.web_clone.adapter import WebCloneAdapter, get_pending_messages, reset_outbox

    reset_outbox()
    adapter = WebCloneAdapter()
    audio_data = b"fake_opus_audio_bytes"

    msg_id = asyncio.get_event_loop().run_until_complete(
        adapter.send_audio("919876543210", audio_data)
    )

    pending = get_pending_messages("919876543210")
    assert len(pending) == 1
    assert pending[0]["type"] == "audio"
    assert pending[0]["content"]["mime_type"] == "audio/ogg; codecs=opus"

    # Verify base64 round-trip
    decoded = base64.b64decode(pending[0]["content"]["data"])
    assert decoded == audio_data
    reset_outbox()


# ---------------------------------------------------------------------------
# Message model tests
# ---------------------------------------------------------------------------

def test_voice_message_type():
    """IncomingMessage supports voice message type with media fields."""
    msg = make_voice_msg()
    assert msg.msg_type == MessageType.VOICE
    assert msg.text is None
    assert msg.media_url == "https://example.com/voice.ogg"
    assert msg.media_id == "media_123"
