# Code signing policy

## Current status

Violet Relay public betas are currently unsigned. Release notes state this
clearly and publish SHA-256 checksums for independent verification.

The project intends to apply for the free open-source signing service provided
by SignPath. Once accepted, the release page will use the required attribution:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

No release will claim to be SignPath-signed before enrollment is approved and
the attached artifact has a valid signature.

## Roles

- Committer and reviewer: [@ruhbyook](https://github.com/ruhbyook)
- Signing approver: [@ruhbyook](https://github.com/ruhbyook)

Signing requests must originate from the public repository's protected release
workflow and correspond to a tagged, reviewed source revision. Repository and
signing accounts must use multi-factor authentication.

## Privacy

See [PRIVACY.md](PRIVACY.md). Violet Relay does not transfer information to
developer-operated systems. Network access occurs only for features requested
by the user, including local Apple TV discovery/casting, direct media URLs, and
the optional verified media-tools installation.
