from pathlib import Path

import pytest

from violetrelay.controllers.windows_integration import WindowsIntegrationController
from violetrelay.services.windows_integration import (
    APPLICATION_PATH,
    CAPABILITIES_PATH,
    LEGACY_APPLICATION_PATH,
    LEGACY_CAPABILITIES_PATH,
    LEGACY_PROG_ID,
    LEGACY_PROG_ID_PATH,
    LEGACY_REGISTRATIONS,
    LEGACY_REGISTERED_NAME,
    PROG_ID,
    PROG_ID_PATH,
    REELFERRY_APPLICATION_PATH,
    REELFERRY_CAPABILITIES_PATH,
    REELFERRY_PROG_ID,
    REELFERRY_PROG_ID_PATH,
    REELFERRY_REGISTERED_NAME,
    REGISTERED_APPS_PATH,
    REGISTERED_NAME,
    VIDEO_EXTENSIONS,
    WindowsDefaultApps,
)


class MemoryRegistry:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_value(self, path: str, name: str = "") -> str | None:
        return self.values.get((path, name))

    def set_value(self, path: str, name: str, value: str) -> None:
        self.values[(path, name)] = value

    def delete_value(self, path: str, name: str) -> None:
        self.values.pop((path, name), None)

    def delete_tree(self, path: str) -> None:
        prefix = path + "\\"
        self.values = {
            key: value
            for key, value in self.values.items()
            if key[0] != path and not key[0].startswith(prefix)
        }


def service(executable: Path, store: MemoryRegistry, opened=None, notified=None):
    opened = opened if opened is not None else []
    notified = notified if notified is not None else []
    return WindowsDefaultApps(
        executable,
        store,
        opener=opened.append,
        notifier=lambda: notified.append(True),
    )


def test_registers_complete_per_user_capabilities(tmp_path):
    registry = MemoryRegistry()
    opened: list[str] = []
    notified: list[bool] = []
    executable = tmp_path / "VioletRelay.exe"
    integration = service(executable, registry, opened, notified)

    assert not integration.state().registered
    state = integration.register()
    assert state.registered and not state.needs_repair
    assert state.open_with_registered
    assert registry.get_value(REGISTERED_APPS_PATH, REGISTERED_NAME) == CAPABILITIES_PATH
    assert registry.get_value(PROG_ID_PATH + r"\shell\open\command") == (
        f'"{executable.resolve()}" "%1"'
    )
    for extension in VIDEO_EXTENSIONS:
        assert (
            registry.get_value(
                CAPABILITIES_PATH + r"\FileAssociations", extension
            )
            == PROG_ID
        )
        assert registry.get_value(
            APPLICATION_PATH + r"\SupportedTypes", extension
        ) == ""
        assert registry.get_value(
            integration._open_with_progids_path(extension), PROG_ID
        ) == ""
    assert registry.get_value(LEGACY_PROG_ID_PATH) is None
    assert notified == [True]


def test_open_with_registration_does_not_claim_default_capabilities(tmp_path):
    registry = MemoryRegistry()
    notified: list[bool] = []
    integration = service(
        tmp_path / "VioletRelay.exe",
        registry,
        notified=notified,
    )

    state = integration.register_open_with()

    assert state.open_with_registered
    assert not state.registered
    assert not state.needs_repair
    assert registry.get_value(REGISTERED_APPS_PATH, REGISTERED_NAME) is None
    for extension in VIDEO_EXTENSIONS:
        assert registry.get_value(
            integration._open_with_progids_path(extension), PROG_ID
        ) == ""
    assert notified == [True]


def test_moved_portable_folder_is_detected_and_repaired(tmp_path):
    registry = MemoryRegistry()
    first = service(tmp_path / "old" / "VioletRelay.exe", registry)
    first.register()
    moved = service(tmp_path / "new" / "VioletRelay.exe", registry)
    assert moved.state().needs_repair
    assert not moved.register().needs_repair
    assert str((tmp_path / "new").resolve()) in registry.get_value(
        PROG_ID_PATH + r"\shell\open\command"
    )


def test_moved_open_with_registration_is_detected_and_repaired(tmp_path):
    registry = MemoryRegistry()
    first = service(tmp_path / "old" / "VioletRelay.exe", registry)
    first.register_open_with()
    moved = service(tmp_path / "new" / "VioletRelay.exe", registry)

    assert moved.state().needs_repair
    state = moved.register_open_with()

    assert state.open_with_registered
    assert not state.needs_repair
    assert str((tmp_path / "new").resolve()) in registry.get_value(
        APPLICATION_PATH + r"\shell\open\command"
    )


@pytest.mark.parametrize(
    ("registered_name", "capabilities_path", "prog_id", "prog_id_path", "application_path"),
    (
        (
            REELFERRY_REGISTERED_NAME,
            REELFERRY_CAPABILITIES_PATH,
            REELFERRY_PROG_ID,
            REELFERRY_PROG_ID_PATH,
            REELFERRY_APPLICATION_PATH,
        ),
        (
            LEGACY_REGISTERED_NAME,
            LEGACY_CAPABILITIES_PATH,
            LEGACY_PROG_ID,
            LEGACY_PROG_ID_PATH,
            LEGACY_APPLICATION_PATH,
        ),
    ),
)
def test_legacy_registration_is_migrated_without_breaking_old_defaults(
    tmp_path,
    registered_name,
    capabilities_path,
    prog_id,
    prog_id_path,
    application_path,
):
    registry = MemoryRegistry()
    executable = tmp_path / "VioletRelay.exe"
    integration = service(executable, registry)
    legacy_command = '"C:\\old\\xMediaPlayerx.exe" "%1"'
    registry.set_value(
        REGISTERED_APPS_PATH,
        registered_name,
        capabilities_path,
    )
    registry.set_value(
        prog_id_path + r"\shell\open\command",
        "",
        legacy_command,
    )
    registry.set_value(
        application_path + r"\shell\open\command",
        "",
        legacy_command,
    )
    for extension in VIDEO_EXTENSIONS:
        registry.set_value(
            integration._open_with_progids_path(extension),
            prog_id,
            "",
        )

    before = integration.state()
    assert before.registered
    assert before.needs_repair

    after = integration.register()

    assert after.registered
    assert after.open_with_registered
    assert not after.needs_repair
    assert registry.get_value(
        REGISTERED_APPS_PATH,
        registered_name,
    ) is None
    assert registry.get_value(application_path) is None
    assert registry.get_value(
        prog_id_path + r"\shell\open\command"
    ) == f'"{executable.resolve()}" "%1"'
    for extension in VIDEO_EXTENSIONS:
        assert registry.get_value(
            integration._open_with_progids_path(extension),
            prog_id,
        ) is None


def test_opens_app_specific_default_settings_and_unregisters(tmp_path):
    registry = MemoryRegistry()
    opened: list[str] = []
    integration = service(tmp_path / "VioletRelay.exe", registry, opened)
    integration.register()
    uri = integration.open_default_apps()
    assert uri == "ms-settings:defaultapps?registeredAppUser=Violet%20Relay"
    assert opened == [uri]
    integration.unregister()
    assert not integration.state().registered
    assert registry.get_value(PROG_ID_PATH) is None


def test_controller_registers_before_opening_settings(qtbot, tmp_path):
    registry = MemoryRegistry()
    opened: list[str] = []
    integration = service(tmp_path / "VioletRelay.exe", registry, opened)
    controller = WindowsIntegrationController(integration)
    with qtbot.waitSignal(controller.changed):
        controller.registerAndChooseDefaults()
    assert controller.registered
    assert "choose" in controller.statusText.lower()
    assert opened and opened[0].startswith("ms-settings:defaultapps")


def test_controller_automatically_registers_only_for_open_with(qtbot, tmp_path):
    registry = MemoryRegistry()
    opened: list[str] = []
    integration = service(tmp_path / "VioletRelay.exe", registry, opened)
    controller = WindowsIntegrationController(integration)

    with qtbot.waitSignal(controller.changed):
        controller.ensureOpenWith()

    assert controller.openWithRegistered
    assert not controller.registered
    assert "open with" in controller.statusText.lower()
    assert not opened


def test_controller_auto_repairs_full_registration_after_portable_move(
    qtbot, tmp_path
):
    registry = MemoryRegistry()
    first = service(tmp_path / "old" / "VioletRelay.exe", registry)
    first.register()
    moved = service(tmp_path / "new" / "VioletRelay.exe", registry)
    controller = WindowsIntegrationController(moved)
    assert controller.needsRepair

    with qtbot.waitSignal(controller.changed):
        controller.ensureOpenWith()

    assert controller.registered
    assert controller.openWithRegistered
    assert not controller.needsRepair
    assert str((tmp_path / "new").resolve()) in registry.get_value(
        CAPABILITIES_PATH, "ApplicationIcon"
    )


def test_controller_explicit_open_with_registration(qtbot, tmp_path):
    registry = MemoryRegistry()
    integration = service(tmp_path / "VioletRelay.exe", registry)
    controller = WindowsIntegrationController(integration)

    with qtbot.waitSignal(controller.changed):
        controller.registerForOpenWith()

    assert controller.openWithRegistered
    assert controller.openWithActionText == "Registered for Open with"


def test_controller_can_remove_open_with_registration(qtbot, tmp_path):
    registry = MemoryRegistry()
    integration = service(tmp_path / "VioletRelay.exe", registry)
    controller = WindowsIntegrationController(integration)
    controller.registerForOpenWith()

    with qtbot.waitSignal(controller.changed):
        controller.unregister()

    assert not controller.openWithRegistered
    assert not controller.registered


def test_controller_survives_registry_initialization_failure(qtbot):
    class BrokenService:
        def state(self):
            raise PermissionError("registry denied")

    controller = WindowsIntegrationController(BrokenService())
    assert not controller.available
    assert "registry denied" in controller.statusText
    with qtbot.waitSignal(controller.errorOccurred) as signal:
        controller.registerAndChooseDefaults()
    assert "registry denied" in signal.args[0]


def test_unregister_attempts_every_cleanup_after_one_failure(tmp_path):
    class BrokenRegistry(MemoryRegistry):
        def __init__(self):
            super().__init__()
            self.deleted = []

        def delete_value(self, path, name):
            self.deleted.append((path, name))
            raise PermissionError("value locked")

        def delete_tree(self, path):
            self.deleted.append((path, "tree"))

    registry = BrokenRegistry()
    notified = []
    integration = service(
        tmp_path / "VioletRelay.exe", registry, notified=notified
    )
    with pytest.raises(RuntimeError, match="completely removed"):
        integration.unregister()
    assert len(registry.deleted) == (
        4
        + (4 * len(LEGACY_REGISTRATIONS))
        + ((1 + len(LEGACY_REGISTRATIONS)) * len(VIDEO_EXTENSIONS))
    )
    assert notified == [True]
