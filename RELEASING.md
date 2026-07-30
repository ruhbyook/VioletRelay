# Releasing ReelFerry

The normal local build remains the safest way to use the player:

```powershell
.\scripts\test.ps1
.\scripts\build.ps1
```

For an archive clearly labeled as a local beta:

```powershell
.\scripts\release.ps1
```

A public archive is built without bundled FFmpeg executables. The application
offers the pinned upstream download only after the user explicitly agrees:

```powershell
.\scripts\release.ps1 -Public -DistRoot dist-public
```

Before publishing:

1. Keep the version synchronized in `pyproject.toml`,
   `src/reelferry/__init__.py`, and `assets/reelferry-version-info.txt`.
   `tests/test_branding.py` enforces this.
2. Verify every item in the physical Apple TV checklist in `README.md`.
3. Publish the application ZIP, exact application source archive,
   `SHA256SUMS.txt`, license, and notices together on the GitHub release.
4. Publish this application's complete GPL source at the same revision as the
   binary, including build scripts and dependency lock file.
5. Confirm the public ZIP contains no `ffmpeg.exe` or `ffprobe.exe`. Review
   Qt/PySide obligations and codec-patent rules for the places where the build
   is offered. This project does not provide legal advice.
6. Code-signing is strongly recommended before inviting nontechnical users.
7. Test on a clean Windows 11 user account and with a new Apple TV pairing.
8. Confirm the in-app and README support addresses match
   `src/reelferry/support.py`. Keep tips optional and outside the playback
   flow, and never imply tax deductibility, Apple certification, or endorsement.
9. Create an annotated `v<version>` tag from the exact clean revision and
   publish release notes that state whether the artifact is signed.

Do not publish capture logs, `%LOCALAPPDATA%\ReelFerry`, pairing data, cached
media, or `.tools` artifacts.
