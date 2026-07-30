# Privacy

ReelFerry does not include telemetry, advertising, analytics, accounts, or
developer-operated cloud services. The project maintainer does not receive
playback history, filenames, pairing credentials, diagnostic logs, or media
URLs from the application.

## Network activity

ReelFerry accesses the network only for features initiated by the user:

- scanning the local network for Apple TV devices;
- pairing with and controlling a selected Apple TV;
- temporarily serving selected media to that Apple TV over the local network;
- opening a direct HTTP/HTTPS media URL supplied by the user; and
- downloading the optional FFmpeg media tools after the user chooses
  **Install**.

The media-tools archive is downloaded directly from the upstream Windows FFmpeg
build provider's GitHub release. GitHub and the provider receive normal network
request information such as the user's IP address. Their privacy policies apply
to that request.

The optional support dialog is entirely static and offline. It displays public
receiving addresses and locally bundled QR images; ReelFerry does not connect
to a wallet, exchange, blockchain service, or project-operated payment service.
Copying an address uses only the local Windows clipboard.

Local media is served from a random, unguessable URL on an ephemeral port and
only while a cast session needs it. ReelFerry does not upload local media to
the project maintainer.

## Data stored locally

Depending on features used, ReelFerry stores:

- window, volume, cache, and preferred-device settings;
- resume positions for local media;
- Apple TV pairing credentials encrypted with Windows DPAPI for the current
  Windows user;
- prepared cast media and temporary streaming segments;
- the verified FFmpeg tools if the user installs them; and
- rotating diagnostic logs with credential and URL-query redaction.

These files are stored below the Windows local application-data directories for
`ReelFerry`. The Settings panel can clear the prepared cast cache and remove
Windows file integration. Deleting the ReelFerry local application-data
directories after closing the program removes all remaining local data,
including pairing credentials, resume history, tools, and logs.

When upgrading from the former xMediaPlayerx name, ReelFerry performs a local
one-time move from `%LOCALAPPDATA%\xMediaPlayerx` to
`%LOCALAPPDATA%\ReelFerry`. Nothing is transmitted during this migration.

## Bug reports

Diagnostic logs can still contain filenames, local paths, device names, network
addresses, and media titles. Review and redact them before posting. Never
publish pairing files or raw network captures.

Questions and privacy problems can be reported through the repository's issue
tracker. Security-sensitive reports should use GitHub's private vulnerability
reporting feature.
