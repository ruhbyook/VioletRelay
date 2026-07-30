from __future__ import annotations

import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import shutil


LICENSE_NAMES = re.compile(
    r"^(license|licence|copying|notice|authors|copyright)(\..*)?$", re.IGNORECASE
)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_") or "unknown"


def is_license_file(path: Path) -> bool:
    return bool(LICENSE_NAMES.match(path.name)) or any(
        part.lower() in {"license", "licenses", "licence", "licences"}
        for part in path.parts
    )


def collect(output: Path) -> list[dict[str, object]]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []

    for distribution in sorted(
        metadata.distributions(),
        key=lambda item: (item.metadata.get("Name", "").lower(), item.version),
    ):
        name = distribution.metadata.get("Name") or "unknown"
        if name.lower().replace("-", "") == "violetrelay":
            # The project's GPL text is copied to the release root separately.
            continue
        package_dir = output / f"{safe_name(name)}-{safe_name(distribution.version)}"
        copied: list[str] = []
        for entry in distribution.files or ():
            relative = Path(str(entry))
            if not is_license_file(relative):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            # Flatten paths and include a short hash-like suffix on collisions.
            target_name = safe_name("__".join(relative.parts[-3:]))
            target = package_dir / target_name
            index = 2
            while target.exists() and target.read_bytes() != source.read_bytes():
                target = package_dir / f"{target_name}.{index}"
                index += 1
            package_dir.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            copied.append(str(target.relative_to(output)))

        manifest.append(
            {
                "name": name,
                "version": distribution.version,
                "license_expression": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or "not declared in package metadata",
                "license_files": sorted(set(copied)),
            }
        )

    (output / "DEPENDENCY_LICENSES.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect installed Python dependency license notices"
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = collect(args.output.resolve())
    missing = [item["name"] for item in manifest if not item["license_files"]]
    print(f"Collected license metadata for {len(manifest)} distributions.")
    if missing:
        print("No packaged license file found for: " + ", ".join(map(str, missing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
