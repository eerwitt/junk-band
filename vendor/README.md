# Pinned JavaScript packages

These are unmodified npm release archives copied from the machine's existing npm cache. They allow reproducible offline installation with `npm ci --offline --ignore-scripts --cache .npm-cache --no-audit --no-fund`. SHA-512 integrity is recorded in the root lockfile.

| Package | Version | Purpose | Upstream license |
| --- | --- | --- | --- |
| Zod | 4.1.8 | Runtime project, command and response validation | MIT, included in archive |
| TypeScript | 5.9.3 | Development compiler and strict checks | Apache-2.0, included in archive |
| Prettier | 2.8.8 | Development formatter | MIT, included in archive |

There are no transitive npm packages. Godot's engine/export templates are installed separately; gated model weights are never vendored. Review and replace these archives deliberately when updating dependencies.
