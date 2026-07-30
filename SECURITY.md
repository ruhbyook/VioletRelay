# Security policy

## Supported versions

Security fixes are provided for the latest published beta. Older portable
builds should be replaced rather than retained.

## Reporting a vulnerability

Use
[GitHub private vulnerability reporting](https://github.com/ruhbyook/ReelFerry/security/advisories/new).
Do not open a public issue for credential exposure, arbitrary file access,
command execution, unsafe update/download behavior, or network-service flaws.

Include the affected version, reproduction steps, impact, and a minimal
proof-of-concept. Do not include Apple TV pairing credentials, copyrighted
media, third-party access tokens, or unrelated personal data.

The maintainer will acknowledge a useful report as soon as practical, keep
discussion private while a fix is prepared, and credit the reporter if desired.

## Release integrity

Every release publishes SHA-256 checksums. Public binaries are built from a
tagged revision. Until trusted code signing is available, releases are clearly
identified as unsigned. The optional FFmpeg download is accepted only when the
archive and extracted executable hashes match pinned values.

The canonical optional-support addresses are committed in
`src/reelferry/support.py` and repeated in the tagged README. Treat an
unexpected donation-address change as a security-sensitive supply-chain event
and report it privately.
