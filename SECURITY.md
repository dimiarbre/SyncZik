# Security Policy

SyncZik is a personal-scale tool: a local TUI/CLI that stores OAuth
tokens and playlist data on your own machine. There's no server
component and no user data ever leaves your machine except to talk
directly to the Spotify/Deezer APIs on your behalf.

## Supported versions

There are no tagged releases yet — only `main` is supported. Please make
sure you're running the latest commit before reporting an issue.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security
vulnerability. Instead, use GitHub's private reporting:

1. Go to the [Security tab](https://github.com/dimiarbre/SyncZik/security) of this repository.
2. Click "Report a vulnerability" to open a private advisory.

This is the preferred channel because it lets us discuss and fix the
issue before it's public. We'll acknowledge reports as soon as we can
and keep you updated as a fix is worked out.

## Scope

Of particular interest:

- Handling of Spotify/Deezer OAuth tokens (`.spotify_cache`,
  `DEEZER_ACCESS_TOKEN`) — currently stored as plaintext on disk, which is
  a known limitation (see the README roadmap) rather than something to
  report as a new finding, unless you've found a way to exfiltrate or
  leak it beyond what plaintext-on-your-own-machine already implies.
- Anything that could make SyncZik read, modify, or delete files outside
  its own data directory, or send data to somewhere other than the
  Spotify/Deezer APIs it's configured to talk to.
