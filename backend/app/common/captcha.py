"""A self-hosted image CAPTCHA with no third-party service and no image library.

M1 VRFY_ABHA_301 asks for a second check on the mobile ABHA lookup ("Captcha
preferred"). A government deployment should not send each desk request to an
outside CAPTCHA provider, and the backend has no imaging dependency, so this
draws five characters from a small bitmap font, shears and jitters each one,
adds noise, and encodes a greyscale PNG with zlib.

Only a digest of the answer is kept, in Redis, for five minutes, and a
challenge is spent by its first check whether right or wrong: a wrong answer
gets a new image, never a second guess at the same one.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import zlib

from app.common.redis import get_redis

#: No 0/O, 1/I/L, 5/S or 2/Z: a desk reading a noisy image should not have to guess.
ALPHABET = "ABCDEFGHJKMNPQRTUVWXY346789"
LENGTH = 5
TTL_SECONDS = 300
WIDTH, HEIGHT = 170, 56

# 5x7 glyphs, one string per row, "#" is ink.
_GLYPHS = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "J": ["..###", "...#.", "...#.", "...#.", "#..#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "3": ["####.", "....#", "....#", ".###.", "....#", "....#", "####."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
}
assert set(_GLYPHS) == set(ALPHABET)


def _key(captcha_id: str) -> str:
    return f"captcha:{captcha_id}"


def _digest(captcha_id: str, answer: str) -> str:
    normalised = "".join(answer.split()).upper()
    return hashlib.sha256(f"{captcha_id}:{normalised}".encode()).hexdigest()


def render(text: str, rng: secrets.SystemRandom | None = None) -> bytes:
    """A greyscale PNG of `text` with per-glyph shear, jitter and noise."""
    rng = rng or secrets.SystemRandom()
    canvas = [[235 + rng.randrange(20) for _ in range(WIDTH)] for _ in range(HEIGHT)]
    scale, step = 5, WIDTH // (LENGTH + 1)
    for index, char in enumerate(text):
        left = 10 + index * step + rng.randrange(-3, 4)
        top = 8 + rng.randrange(-4, 5)
        shear = rng.uniform(-0.35, 0.35)
        ink = rng.randrange(20, 90)
        for row, line in enumerate(_GLYPHS[char]):
            for col, cell in enumerate(line):
                if cell != "#":
                    continue
                for dy in range(scale):
                    for dx in range(scale - 1):
                        y = top + row * scale + dy
                        x = left + col * (scale - 1) + dx + int(shear * (y - HEIGHT / 2))
                        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                            canvas[y][x] = ink
    for _ in range(4):  # strike-through lines
        y, slope = rng.randrange(HEIGHT), rng.uniform(-0.3, 0.3)
        for x in range(WIDTH):
            yy = int(y + slope * x)
            if 0 <= yy < HEIGHT:
                canvas[yy][x] = rng.randrange(60, 160)
    for _ in range(WIDTH * HEIGHT // 12):  # speckle
        canvas[rng.randrange(HEIGHT)][rng.randrange(WIDTH)] = rng.randrange(256)
    raw = b"".join(b"\x00" + bytes(row) for row in canvas)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 0, 0, 0, 0)  # 8-bit greyscale
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


async def issue() -> tuple[str, bytes]:
    """A new challenge: its id and image. The answer itself is never stored."""
    rng = secrets.SystemRandom()
    text = "".join(rng.choice(ALPHABET) for _ in range(LENGTH))
    captcha_id = secrets.token_urlsafe(18)
    await get_redis().set(_key(captcha_id), _digest(captcha_id, text), ex=TTL_SECONDS)
    return captcha_id, render(text, rng)


async def check(captcha_id: str | None, answer: str | None) -> bool:
    """Spend the challenge and say whether the answer matched it."""
    if not captcha_id or not answer or len(captcha_id) > 64 or len(answer) > 16:
        return False
    redis = get_redis()
    stored = await redis.get(_key(captcha_id))
    await redis.delete(_key(captcha_id))
    if stored is None:
        return False
    stored = stored.decode() if isinstance(stored, bytes) else str(stored)
    return hmac.compare_digest(stored, _digest(captcha_id, answer))
