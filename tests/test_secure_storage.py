import asyncio
import json
import os

import pytest

from xmediaplayerx.services.secure_storage import SecureFileStorage


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI test")


def test_plaintext_pairing_storage_is_migrated_without_data_loss(tmp_path):
    async def scenario():
        path = tmp_path / "pyatv.json"
        original = {"version": 1, "devices": []}
        path.write_text(json.dumps(original), encoding="utf-8")

        first = SecureFileStorage(str(path), asyncio.get_running_loop())
        await first.load()
        encrypted = path.read_text(encoding="utf-8")

        second = SecureFileStorage(str(path), asyncio.get_running_loop())
        await second.load()
        return original, dict(first), dict(second), encrypted

    original, first, second, encrypted = asyncio.run(scenario())
    assert first == original
    assert second == original
    assert encrypted.startswith("XMEDIAPLAYERX-DPAPI-1\n")
    assert '"devices"' not in encrypted


def test_corrupt_encrypted_pairing_storage_is_quarantined_for_repair(tmp_path):
    async def scenario():
        path = tmp_path / "pyatv.json"
        original = "XMEDIAPLAYERX-DPAPI-1\nnot-base64\n"
        path.write_text(original, encoding="utf-8")
        storage = SecureFileStorage(str(path), asyncio.get_running_loop())
        await storage.load()
        quarantined = list(tmp_path.glob("pyatv.json.unreadable-*"))
        return path.exists(), quarantined, original

    exists, quarantined, original = asyncio.run(scenario())
    assert not exists
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == original
