# HM-Arch v2.0.2

HM-Arch **2.0.2** is a patch release for smooth Hermes uninstall support.

## Fixes

- `hm-arch uninstall hermes` now removes HM-Arch-owned Hermes provider settings
  instead of returning `unsupported`.
- `hm-arch-install uninstall hermes` now works through the npm installer path.
- Hermes uninstall is idempotent: repeating the command reports that HM-Arch is
  already not installed.
- Hermes uninstall removes the HM-Arch plugin bridge and preserves existing
  memory databases by default.
- Hermes uninstall preserves unrelated Hermes memory providers and plugin
  configuration.

## Verification

- Hermes install/uninstall CLI regression tests.
- Hermes worker-thread provider tests.
- Full offline test suite before release.

## Install

```bash
pip install hm-arch==2.0.2
npm install -g @hm-arch/installer@2.0.2
```
