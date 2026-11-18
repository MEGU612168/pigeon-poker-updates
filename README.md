# Pigeon Poker Update Channel

This public repository hosts only versioned update packages and the stable-channel manifest for Pigeon Poker.

- Stable manifest: `stable.json`
- Update packages: `releases/<version>/payload-updater.zip.b64` (Base64 transport; SHA-256 and size in the manifest refer to the decoded ZIP bytes)

The application downloads the manifest and package over HTTPS, verifies the package SHA-256 digest, validates the allowed file list, backs up replaced application files, and leaves local user data outside the update scope.

Do not place personal data, wallet records, hand histories, Focus Timer records, or strategy databases in this repository.
