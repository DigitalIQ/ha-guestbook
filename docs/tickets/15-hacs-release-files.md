# 15: HACS and release files

**What to build:** The repository passes HACS and Hassfest validation and can be added to HACS as a custom repository.

**Blocked by:** 06, 07, 10, 11, 12, 13, 14

**Status:** ready-for-agent

- [ ] `hacs.json` with name and minimum Home Assistant version
- [ ] `manifest.json` complete (domain, name, version, documentation, issue_tracker, codeowners, config_flow, iot_class, integration_type)
- [ ] `brand/icon.png` (256 px) and `brand/icon@2x.png` (512 px) in the integration folder
- [ ] README in English with setup, entities, events, actions, example automations, privacy section
- [ ] MIT `LICENSE`, translations `en` and `de` complete, `services.yaml` complete
- [ ] GitHub Actions: HACS action and Hassfest
- [ ] Full test suite green
