"""Voice service -- STT (transcribe incoming) + TTS (generate voice replies).

Uses OpenAI gpt-4o-transcribe for speech-to-text and gpt-4o-mini-tts for
text-to-speech with style prompting (warm Hinglish salesperson tone).

WhatsApp sends voice notes as OGG/Opus. OpenAI STT accepts mp3, mp4, mpeg,
mpga, m4a, wav, webm -- so we convert OGG to WAV via ffmpeg.

TTS outputs Opus directly (native WhatsApp voice note format).
"""

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from openai import AsyncOpenAI

import config

log = logging.getLogger("vyapari.services.voice")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# OGG -> WAV conversion (ffmpeg)
# ---------------------------------------------------------------------------

def _convert_ogg_to_wav(ogg_bytes: bytes) -> bytes:
    """Convert OGG/Opus audio to WAV using ffmpeg.

    Raises RuntimeError if ffmpeg is not available or conversion fails.
    """
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_f:
        ogg_f.write(ogg_bytes)
        ogg_path = ogg_f.name

    wav_path = ogg_path.replace(".ogg", ".wav")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", ogg_path,
                "-ar", "16000",     # 16kHz sample rate (good for speech)
                "-ac", "1",         # mono
                "-f", "wav",
                wav_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"ffmpeg conversion failed: {stderr}")

        return Path(wav_path).read_bytes()

    finally:
        # Clean up temp files
        for p in (ogg_path, wav_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Speech-to-Text (incoming voice notes)
# ---------------------------------------------------------------------------

_STT_PROMPT = (
    "Hinglish conversation about cars, prices, bookings, test drives. "
    "Common words: Nexon, Harrier, Tata, Maruti, Hyundai, Honda, Toyota, "
    "Mahindra, Kia, kitna, price, EMI, test drive, booking, token, lakh, "
    "petrol, diesel, automatic, manual, kilometre, showroom."
)


async def transcribe_voice_note(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
) -> str:
    """Transcribe a voice note to text.

    Args:
        audio_bytes: Raw audio bytes (typically OGG/Opus from WhatsApp).
        mime_type: MIME type of the input audio.

    Returns:
        Transcribed text string.

    Raises:
        RuntimeError: If transcription fails.
    """
    client = _get_client()

    # Convert OGG to WAV if needed (OpenAI doesn't accept OGG)
    if "ogg" in mime_type or "opus" in mime_type:
        log.info("Converting OGG/Opus to WAV for transcription")
        wav_bytes = _convert_ogg_to_wav(audio_bytes)
        file_tuple = ("voice.wav", wav_bytes, "audio/wav")
    elif "webm" in mime_type:
        file_tuple = ("voice.webm", audio_bytes, "audio/webm")
    elif "mp3" in mime_type or "mpeg" in mime_type:
        file_tuple = ("voice.mp3", audio_bytes, "audio/mpeg")
    elif "wav" in mime_type:
        file_tuple = ("voice.wav", audio_bytes, "audio/wav")
    elif "m4a" in mime_type or "mp4" in mime_type:
        file_tuple = ("voice.m4a", audio_bytes, "audio/mp4")
    else:
        # Best effort: try as WAV after conversion
        log.warning(f"Unknown audio MIME type {mime_type}, attempting OGG conversion")
        wav_bytes = _convert_ogg_to_wav(audio_bytes)
        file_tuple = ("voice.wav", wav_bytes, "audio/wav")

    try:
        transcription = await client.audio.transcriptions.create(
            model=config.OPENAI_STT_MODEL,
            file=file_tuple,
            response_format="text",
            prompt=_STT_PROMPT,
        )

        text = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
        log.info(f"Transcribed voice note ({len(audio_bytes)} bytes): {text[:100]}...")
        return text

    except Exception as e:
        log.error(f"Voice transcription failed: {e}", exc_info=True)
        raise RuntimeError(f"Failed to transcribe voice note: {e}") from e


# ---------------------------------------------------------------------------
# Text-to-Speech (outgoing voice replies)
# ---------------------------------------------------------------------------

_TTS_INSTRUCTIONS = (
    "Speak in a warm, friendly, natural Hinglish tone -- like a helpful car "
    "salesperson chatting on WhatsApp. Be conversational, not robotic. "
    "Mix Hindi and English naturally. Keep a steady, clear pace."
)


async def generate_voice_reply(
    text: str,
    instructions: str | None = None,
) -> bytes:
    """Convert text to spoken audio (Opus format for WhatsApp).

    Args:
        text: The text to convert to speech.
        instructions: Optional style prompt override for the TTS model.

    Returns:
        Audio bytes in OGG/Opus format.
    """
    client = _get_client()

    try:
        response = await client.audio.speech.create(
            model=config.OPENAI_TTS_MODEL,
            voice=config.OPENAI_TTS_VOICE,
            input=text,
            instructions=instructions or _TTS_INSTRUCTIONS,
            response_format="opus",
        )

        audio_bytes = response.content
        log.info(f"Generated voice reply: {len(audio_bytes)} bytes, {len(text)} chars input")
        return audio_bytes

    except Exception as e:
        log.error(f"TTS generation failed: {e}", exc_info=True)
        raise RuntimeError(f"Failed to generate voice reply: {e}") from e
