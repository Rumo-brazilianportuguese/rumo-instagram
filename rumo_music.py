"""Original background music for the Reels, made from scratch by this kit.

Nothing is sampled or copied: every note is synthesised here from sine waves
and noise (soft electric piano, bass, shaker, rim click), on simple jazz and
bossa chord progressions. So there is no copyright claim on it. Each Reel gets
its own variation (key, tempo, progression, groove), and the countdown ticks
and the 'answer' chime are placed exactly on the Reel's own timeline.
"""
import hashlib
import math
import wave

import numpy as np

SR = 44100

CHORDS = {
    "maj7": (0, 4, 7, 11), "maj9": (0, 4, 7, 11, 14), "m7": (0, 3, 7, 10), "m9": (0, 3, 7, 10, 14),
    "dom7": (0, 4, 7, 10), "dom9": (0, 4, 7, 10, 14), "6": (0, 4, 7, 9),
}
PROGRESSIONS = [
    [(0, "maj9"), (9, "m7"), (2, "m9"), (7, "dom9")],     # I  vi  ii  V
    [(2, "m9"), (7, "dom9"), (0, "maj9"), (5, "maj7")],   # ii V   I   IV
    [(0, "maj7"), (5, "maj7"), (4, "m7"), (9, "m7")],     # I  IV  iii vi
    [(5, "maj9"), (4, "m7"), (2, "m9"), (0, "6")],        # IV iii ii  I
    [(9, "m9"), (2, "m9"), (7, "dom9"), (0, "maj9")],     # vi ii  V   I
    [(0, "maj9"), (2, "m7"), (4, "m7"), (5, "maj7")],     # I  ii  iii IV
]
KEYS = [0, 2, 3, 5, 7, 8, 10]           # C D Eb F G Ab Bb (root of the key, as MIDI offset)
# 16 steps per bar. Bossa comping alternates two bars; the lo-fi feel holds chords.
BOSSA_COMP = ([0, 3, 6, 10, 12], [2, 4, 8, 11, 14])
BOSSA_BASS = [(0, 0, 0.55), (6, 0, 0.2), (8, 7, 0.55), (14, 7, 0.2)]   # step, interval, length (beats)
CLAVE = ([0, 3, 6, 10, 13], [2, 6, 10, 12])


def _midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n, attack, tau, release):
    t = np.arange(n) / SR
    e = np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / tau)
    r = int(release * SR)
    if r and n > r:
        e[-r:] *= np.linspace(1.0, 0.0, r)
    elif n:
        e *= np.linspace(1.0, 0.0, n)
    return e


def _keys_note(f, dur, vel):
    n = int(dur * SR)
    t = np.arange(n) / SR
    body = (np.sin(2 * np.pi * f * t)
            + 0.32 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.45)
            + 0.10 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / 0.22))
    tine = 0.07 * np.sin(2 * np.pi * 7.02 * f * t) * np.exp(-t / 0.05) if f < 900 else 0
    return vel * (body + tine) * _env(n, 0.006, 1.4, 0.09)


def _bass_note(f, dur, vel):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(2 * np.pi * 2 * f * t)
    return vel * np.tanh(1.3 * x) * _env(n, 0.005, 0.6, 0.06)


def _noise_hit(rng, dur, tau, vel, bright=True):
    n = int(dur * SR)
    x = rng.standard_normal(n)
    if bright:
        x = np.diff(np.diff(x, prepend=0), prepend=0) * 0.5
    return vel * x * _env(n, 0.001, tau, 0.004)


def _rim(dur, vel):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 1750 * t) * np.exp(-t / 0.018) + 0.4 * np.sin(2 * np.pi * 820 * t) * np.exp(-t / 0.03)
    return vel * x * _env(n, 0.0008, 0.05, 0.004)


def _kick(vel):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    f = 48 + 60 * np.exp(-t / 0.03)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return vel * np.sin(ph) * _env(n, 0.002, 0.11, 0.02)


def _tick(vel):
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 2100 * t) + 0.5 * np.sin(2 * np.pi * 3150 * t)
    return vel * x * _env(n, 0.0008, 0.022, 0.01)


def _chime(root_midi, vel):
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for k, (iv, a) in enumerate(((0, 1.0), (7, 0.7), (12, 0.45), (16, 0.25))):
        f = _midi(root_midi + iv)
        x += a * np.sin(2 * np.pi * f * t + k) * np.exp(-t / (0.55 - 0.08 * k))
    return vel * x * _env(n, 0.003, 1.2, 0.2)


def _add(buf, start_s, sig, pan=0.0):
    i = int(round(start_s * SR))
    if i >= buf.shape[1] or len(sig) == 0:
        return
    j = min(buf.shape[1], i + len(sig))
    s = sig[: j - i]
    l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
    buf[0, i:j] += s * l * 1.414
    buf[1, i:j] += s * r * 1.414


def _voicing(key, deg, quality, prev_center=64):
    tones = [(key + deg + iv) % 12 for iv in CHORDS[quality][1:]]  # the root goes to the bass
    notes = []
    for pc in tones:
        cands = [m for m in range(52, 80) if m % 12 == pc]
        notes.append(min(cands, key=lambda m: abs(m - prev_center)))
    return sorted(set(notes))


def make_track(duration, seed, events=(), path=None):
    """Write a stereo 16-bit WAV of `duration` seconds and return the path.

    events: (time_s, 'tick' | 'chime') placed on the Reel's own timeline.
    """
    h = int(hashlib.sha256(str(seed).encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(h)
    style = "bossa" if h % 3 else "lofi"
    bpm = (96 + h % 16) if style == "bossa" else (78 + h % 12)
    key = KEYS[h % len(KEYS)]
    prog = PROGRESSIONS[(h // 7) % len(PROGRESSIONS)]
    beat = 60.0 / bpm
    bar = 4 * beat
    step = beat / 4
    swing = 0.0 if style == "bossa" else step * 0.18
    total = duration + 1.5
    buf = np.zeros((2, int(total * SR) + SR))
    nbars = int(math.ceil(total / bar)) + 1
    center = 64
    for b in range(nbars):
        deg, qual = prog[b % len(prog)]
        t0 = b * bar
        voicing = _voicing(key, deg, qual, center)
        center = int(sum(voicing) / len(voicing))
        root = 40 + ((key + deg) % 12 - 4) % 12   # E2..Eb3: audible on phone speakers
        if style == "bossa":
            for s in BOSSA_COMP[b % 2]:
                v = 0.11 if s in (0, 8) else 0.085
                for m in voicing:
                    _add(buf, t0 + s * step + rng.uniform(0, 0.006), _keys_note(_midi(m), beat * 0.9, v),
                         pan=-0.25 + 0.5 * ((m % 5) / 4))
            for s, iv, ln in BOSSA_BASS:
                _add(buf, t0 + s * step, _bass_note(_midi(root + iv), beat * ln * 2, 0.30))
            for s in range(16):
                acc = 0.035 if s % 2 else 0.02
                _add(buf, t0 + s * step, _noise_hit(rng, 0.06, 0.018, acc), pan=0.45)
            for s in CLAVE[b % 2]:
                _add(buf, t0 + s * step, _rim(0.06, 0.06), pan=-0.4)
        else:
            for m in voicing:
                _add(buf, t0, _keys_note(_midi(m), bar * 0.98, 0.085), pan=-0.2 + 0.4 * ((m % 5) / 4))
                _add(buf, t0 + 2 * beat + swing, _keys_note(_midi(m), bar * 0.48, 0.05),
                     pan=0.2 - 0.4 * ((m % 5) / 4))
            _add(buf, t0, _bass_note(_midi(root), bar * 0.5, 0.32))
            _add(buf, t0 + 2.5 * beat, _bass_note(_midi(root + 7), beat * 1.2, 0.24))
            for k in (0, 2):
                _add(buf, t0 + k * beat, _kick(0.42))
            for k in (1, 3):
                _add(buf, t0 + k * beat, _rim(0.08, 0.11), pan=-0.1)
            for s in range(8):
                _add(buf, t0 + s * 2 * step + (swing if s % 2 else 0), _noise_hit(rng, 0.05, 0.014, 0.03),
                     pan=0.4)
    # Level: background music around -18 dBFS RMS, soft limit below -1 dBFS.
    buf = buf[:, : int(duration * SR)]
    rms = float(np.sqrt(np.mean(buf ** 2))) or 1e-9
    buf *= (10 ** (-18 / 20)) / rms
    for t, kind in events:
        if kind == "tick":
            _add(buf, t, _tick(0.16), pan=0.0)
        elif kind == "chime":
            _add(buf, t, _chime(72 + key, 0.14), pan=0.0)
    buf = np.tanh(buf * 1.1) / np.tanh(1.1)
    peak = float(np.max(np.abs(buf))) or 1.0
    if peak > 0.89:
        buf *= 0.89 / peak
    fade_in, fade_out = int(0.02 * SR), int(0.8 * SR)
    buf[:, :fade_in] *= np.linspace(0, 1, fade_in)
    buf[:, -fade_out:] *= np.linspace(1, 0, fade_out)
    pcm = (np.clip(buf, -1, 1) * 32767).astype("<i2").T.copy()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path, {"style": style, "bpm": bpm, "key": key}
