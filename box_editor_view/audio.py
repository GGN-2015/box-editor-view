from __future__ import annotations

from pathlib import Path
import math
import random
import shutil
import struct
import subprocess
import wave


SAMPLE_RATE = 22_050
SOUND_DIR = Path.home() / ".box_editor_view" / "sounds"


def ensure_sound_files() -> dict[str, Path]:
    SOUND_DIR.mkdir(parents=True, exist_ok=True)

    return {
        "place": _ensure_block_sound("place", seed=2015, duration=0.11, pitch=118.0, thump=0.9),
        "break": _ensure_block_sound("break", seed=2016, duration=0.16, pitch=78.0, thump=1.25),
    }


def _ensure_block_sound(name: str, seed: int, duration: float, pitch: float, thump: float) -> Path:
    mp3_path = SOUND_DIR / f"{name}.mp3"
    if mp3_path.exists():
        return mp3_path

    wav_path = SOUND_DIR / f"{name}.wav"
    _write_block_sound(wav_path, seed=seed, duration=duration, pitch=pitch, thump=thump)
    if _convert_wav_to_mp3(wav_path, mp3_path):
        wav_path.unlink(missing_ok=True)
        return mp3_path
    return wav_path


def _convert_wav_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False

    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "5",
            str(mp3_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0 and mp3_path.exists()


def _write_block_sound(path: Path, seed: int, duration: float, pitch: float, thump: float) -> None:
    rng = random.Random(seed)
    samples = int(SAMPLE_RATE * duration)
    frames = bytearray()

    for index in range(samples):
        t = index / SAMPLE_RATE
        envelope = max(0.0, 1.0 - index / samples) ** thump
        noise = rng.uniform(-1.0, 1.0)
        tone = math.sin(2.0 * math.pi * pitch * t)
        click = math.sin(2.0 * math.pi * (pitch * 2.7) * t)
        value = envelope * (0.58 * noise + 0.30 * tone + 0.12 * click)
        frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 22_000)))

    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(SAMPLE_RATE)
        sound.writeframes(bytes(frames))
