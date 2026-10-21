# 15: HACS and release files

**What to build:** The repository passes HACS and Hassfest validation and can be added to HACS as a custom repository.

**Blocked by:** 06, 07, 10, 11, 12, 13, 14

**Status:** ready-for-agent

- [x] `hacs.json` with name and minimum Home Assistant version
- [x] `manifest.json` complete (domain, name, version, documentation, issue_tracker, codeowners, config_flow, iot_class, integration_type)
- [x] `brand/icon.png` (256 px) and `brand/icon@2x.png` (512 px) in the integration folder
- [x] README in English with setup, entities, events, actions, example automations, privacy section
- [x] MIT `LICENSE`, translations `en` and `de` complete, `services.yaml` complete
- [x] GitHub Actions: HACS action and Hassfest
- [x] Full test suite green
