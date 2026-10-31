# -*- coding: utf-8 -*-
import hashlib

from app.api.auth import hash_password, verify_password


def test_bcrypt_roundtrip():
    h = hash_password("secret123")
    assert h.startswith("$2")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong-pass", h) is False


def test_legacy_sha256_fallback():
    # 旧版无盐 sha256 哈希仍可校验，用于平滑迁移
    legacy = hashlib.sha256(("duohe_" + "oldpass").encode("utf-8")).hexdigest()
    assert verify_password("oldpass", legacy) is True
    assert verify_password("wrong-pass", legacy) is False


def test_verify_empty_or_none():
    assert verify_password("x", "") is False
    assert verify_password("x", None) is False
