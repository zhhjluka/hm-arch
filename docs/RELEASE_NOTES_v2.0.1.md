# HM-Arch v2.0.1

HM-Arch **2.0.1** is a patch release for the v2.0 line.

## Fixes

- Fixed Hermes `hm_arch_remember` tool calls when Hermes runs tools from a worker thread.
- Fixed Hermes `hm_arch_search` tool calls under the same threaded execution path.
- Updated Hermes prefetch handling so file-backed SQLite databases are read through fresh handles after explicit tool writes.

## Verification

- Hermes worker-thread regression test for explicit remember/search tool calls.
- Full offline test suite: `1021 passed, 21 deselected`.

## Install

```bash
pip install hm-arch==2.0.1
npm install -g @hm-arch/installer@2.0.1
```
