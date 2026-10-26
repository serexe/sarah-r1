Made a thing: **S.A.R.A.H**, a little voice companion for an R1 running Ubuntu Touch.

It has a native Qt/QML interface with a big tap-to-talk button, an on-screen conversation, and spoken replies. A Python bridge runs the speech models and connects to Codex through Hermes. Optional adapters can work with Home Assistant, SiYuan notes, and Google Calendar once you configure your own accounts.

The idea is pretty simple: a small device you can ask something without opening another app. Speech runs locally on the bridge; conversation still uses a remote backend, so this isn't a fully offline assistant.

It's a hobby project, not a turnkey product. I'm preparing the source under MIT; it needs your own Ubuntu Touch build, bridge setup, and credentials. The screenshot is from a real R1 development build, with the conversation redacted, not a mockup.

Curious whether anyone else finds this neat, or has tried something similar on Ubuntu Touch. Setup feedback and small experiments welcome.
