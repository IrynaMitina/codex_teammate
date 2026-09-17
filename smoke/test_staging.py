"""Explicit remote entry point; never loads tests/conftest.py or the app."""
import os
from urllib.parse import urlsplit

import httpx
import pytest

from smoke.scenario import run_drive_scenario


async def test_drive7_staging():
    required = ("SMOKE_BASE_URL", "SMOKE_ALICE_EMAIL", "SMOKE_ALICE_PASSWORD",
                "SMOKE_BOB_EMAIL", "SMOKE_BOB_PASSWORD", "SMOKE_BOB_USER_ID")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail("Missing smoke settings: " + ", ".join(missing))
    base_url = os.environ["SMOKE_BASE_URL"]
    url = urlsplit(base_url)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        pytest.fail("SMOKE_BASE_URL must be an HTTP(S) URL without credentials")
    try:
        bob_id = int(os.environ["SMOKE_BOB_USER_ID"])
        assert bob_id > 0
    except (ValueError, AssertionError):
        pytest.fail("SMOKE_BOB_USER_ID must be a positive integer")
    if os.environ["SMOKE_ALICE_EMAIL"] == os.environ["SMOKE_BOB_EMAIL"]:
        pytest.fail("Smoke accounts must be distinct")
    async with httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=False) as client:
        await run_drive_scenario(
            client, alice_email=os.environ["SMOKE_ALICE_EMAIL"],
            alice_password=os.environ["SMOKE_ALICE_PASSWORD"],
            bob_email=os.environ["SMOKE_BOB_EMAIL"],
            bob_password=os.environ["SMOKE_BOB_PASSWORD"], bob_user_id=bob_id,
        )
