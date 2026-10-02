"""Self-hosted CAPTCHA for the mobile ABHA lookup (M1 VRFY_ABHA_301, "Captcha preferred")."""

import struct
import zlib

import pytest

from app.common import captcha

pytestmark = pytest.mark.asyncio


class _Redis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def get(self, key):
        found = self.store.get(key)
        return found[0] if found else None

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def redis(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(captcha, "get_redis", lambda: fake)
    return fake


def _answer(fake, captcha_id):
    """Recover the answer by brute force over the digest, as a test oracle only."""
    import itertools

    digest = fake.store[captcha._key(captcha_id)][0]
    for letters in itertools.product(captcha.ALPHABET, repeat=captcha.LENGTH):
        text = "".join(letters)
        if captcha._digest(captcha_id, text) == digest:
            return text
    raise AssertionError("no answer")


def test_the_image_is_a_valid_greyscale_png():
    png = captcha.render("AB346")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    length, kind = struct.unpack(">I4s", png[8:16])
    width, height, depth, colour = struct.unpack(">IIBB", png[16:26])
    assert (kind, width, height, depth, colour) == (b"IHDR", captcha.WIDTH, captcha.HEIGHT, 8, 0)
    idat = png.index(b"IDAT")
    size = struct.unpack(">I", png[idat - 4:idat])[0]
    raw = zlib.decompress(png[idat + 4:idat + 4 + size])
    assert len(raw) == (captcha.WIDTH + 1) * captcha.HEIGHT


def test_two_renders_of_the_same_text_differ():
    assert captcha.render("AB346") != captcha.render("AB346")


async def test_only_a_digest_is_stored_with_an_expiry(redis):
    captcha_id, png = await captcha.issue()
    (value, ttl), = redis.store.values()
    assert ttl == captcha.TTL_SECONDS and len(value) == 64
    assert png.startswith(b"\x89PNG")


async def test_right_answer_passes_once_and_ignores_case_and_spaces(redis, monkeypatch):
    monkeypatch.setattr(captcha, "LENGTH", 2)  # keep the brute-force oracle quick
    captcha_id, _ = await captcha.issue()
    answer = _answer(redis, captcha_id)
    spaced = " ".join(answer).lower()
    assert await captcha.check(captcha_id, spaced) is True
    assert await captcha.check(captcha_id, answer) is False, "a challenge is spent by its first check"


async def test_a_wrong_answer_spends_the_challenge(redis):
    captcha_id, _ = await captcha.issue()
    assert await captcha.check(captcha_id, "?????") is False
    assert redis.store == {}


@pytest.mark.parametrize(("captcha_id", "answer"), [(None, "ABCDE"), ("x", None), ("", ""), ("x" * 65, "A"), ("x", "A" * 17)])
async def test_missing_or_oversized_input_is_refused_without_a_lookup(redis, captcha_id, answer):
    assert await captcha.check(captcha_id, answer) is False


async def test_an_unknown_or_expired_challenge_fails(redis):
    assert await captcha.check("never-issued", "ABCDE") is False
