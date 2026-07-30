import asyncio
import json
import os

import pytest

from violetrelay.services.secure_storage import SecureFileStorage


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
    assert encrypted.startswith("VIOLETRELAY-DPAPI-1\n")
    assert '"devices"' not in encrypted


def test_corrupt_encrypted_pairing_storage_is_quarantined_for_repair(tmp_path):
    async def scenario():
        path = tmp_path / "pyatv.json"
        original = "VIOLETRELAY-DPAPI-1\nnot-base64\n"
        path.write_text(original, encoding="utf-8")
        storage = SecureFileStorage(str(path), asyncio.get_running_loop())
        await storage.load()
        quarantined = list(tmp_path.glob("pyatv.json.unreadable-*"))
        return path.exists(), quarantined, original

    exists, quarantined, original = asyncio.run(scenario())
    assert not exists
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "legacy_header",
    ("REELFERRY-DPAPI-1\n", "XMEDIAPLAYERX-DPAPI-1\n"),
)
def test_legacy_encrypted_pairing_storage_is_rebranded_without_data_loss(
    tmp_path,
    legacy_header,
):
    async def scenario():
        path = tmp_path / "pyatv.json"
        original = {"version": 1, "devices": []}
        path.write_text(json.dumps(original), encoding="utf-8")

        initial = SecureFileStorage(str(path), asyncio.get_running_loop())
        await initial.load()
        legacy = path.read_text(encoding="utf-8").replace(
            "VIOLETRELAY-DPAPI-1\n",
            legacy_header,
            1,
        )
        path.write_text(legacy, encoding="utf-8")

        migrated = SecureFileStorage(str(path), asyncio.get_running_loop())
        await migrated.load()
        return original, dict(migrated), path.read_text(encoding="utf-8")

    original, migrated, encrypted = asyncio.run(scenario())
    assert migrated == original
    assert encrypted.startswith("VIOLETRELAY-DPAPI-1\n")
    assert legacy_header not in encrypted
