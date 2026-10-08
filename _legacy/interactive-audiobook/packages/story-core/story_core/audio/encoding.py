"""Delivery encodings for paragraph audio.

WAV is exact and dependency-free (development). AAC in an MP4 container is ~10x smaller for mobile
delivery and is produced with ffmpeg, which the worker image installs.
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from story_core.audio.pcm import PcmAudio, to_wav


@dataclass(frozen=True, slots=True)
class EncodedAudio:
    data: bytes
    extension: str
    content_type: str


class AudioEncoder(Protocol):
    format_name: str

    async def encode(self, audio: PcmAudio) -> EncodedAudio: ...


class WavEncoder:
    format_name = "wav"

    async def encode(self, audio: PcmAudio) -> EncodedAudio:
        return EncodedAudio(to_wav(audio), "wav", "audio/wav")


class EncoderUnavailable(RuntimeError):
    pass


class FfmpegAacEncoder:
    format_name = "aac"

    def __init__(
        self, *, bitrate: str = "64k", ffmpeg_path: str | None = None, timeout_s: float = 120
    ) -> None:
        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        self._bitrate = bitrate
        self._timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return self._ffmpeg is not None

    async def encode(self, audio: PcmAudio) -> EncodedAudio:
        if self._ffmpeg is None:
            raise EncoderUnavailable("ffmpeg not found")
        # Output goes to a temp file, not a pipe: "+faststart" moves the moov atom to the front, which
        # needs a seekable output and is what lets players start and seek during progressive download.
        with tempfile.TemporaryDirectory(prefix="narration-") as directory:
            target = Path(directory) / "audio.m4a"
            # Arguments are fixed values, never user input.
            process = await asyncio.create_subprocess_exec(
                self._ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "s16le", "-ar", str(audio.sample_rate), "-ac", "1", "-i", "pipe:0",
                "-c:a", "aac", "-b:a", self._bitrate, "-movflags", "+faststart", "-y", str(target),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(audio.samples), timeout=self._timeout_s
                )
            except TimeoutError:
                process.kill()
                raise
            data = await asyncio.to_thread(target.read_bytes) if target.is_file() else b""
        if process.returncode != 0 or not data:
            raise RuntimeError(
                f"ffmpeg failed ({process.returncode}): {stderr[-300:].decode(errors='replace')}"
            )
        return EncodedAudio(data, "m4a", "audio/mp4")


def build_encoder(format_name: str) -> AudioEncoder:
    if format_name == "wav":
        return WavEncoder()
    if format_name == "aac":
        encoder = FfmpegAacEncoder()
        if not encoder.available:
            raise EncoderUnavailable("AUDIO_FORMAT=aac requires ffmpeg on PATH")
        return encoder
    raise ValueError(f"Unknown audio format '{format_name}'")
