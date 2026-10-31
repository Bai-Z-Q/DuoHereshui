# -*- coding: utf-8 -*-
from app.utils.security import create_access_token, decode_token


def test_token_roundtrip():
    token = create_access_token("user-123")
    assert decode_token(token) == "user-123"


def test_invalid_token_returns_none():
    assert decode_token("not-a-valid-token") is None


def test_token_for_uuid_user():
    uid = "00000000-0000-0000-0000-000000000001"
    token = create_access_token(uid)
    assert decode_token(token) == uid
