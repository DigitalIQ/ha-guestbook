# Agent notes

Home Assistant custom integration `guestbook`, published through HACS.

- Spec: `docs/spec.md`. Glossary: `docs/GLOSSARY.md`. Use its terms.
- Issue tracker: local files. One ticket per file in `docs/tickets/NN-slug.md`, numbered in dependency order. Status label `ready-for-agent`. Tick acceptance criteria when done.
- Work the frontier: a ticket whose blockers are all done.
- Build test-first. Seam 1: the pure rule core (no Home Assistant imports). Seam 2: the integration in a test Home Assistant (`pytest-homeassistant-custom-component`, Python 3.14).
- Code, comments, README and commit messages in English.
- Never commit real names, entity ids or data from a real home. Use invented examples.
- Scratch files go to `.tmp/` (git-ignored), not `/tmp`.
