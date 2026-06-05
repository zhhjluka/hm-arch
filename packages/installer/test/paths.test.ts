import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  managedEnvRoot,
  managedHmArchExecutable,
  managedPythonExecutable,
  resolveHmArchHome,
} from "../src/paths.js";

describe("paths", () => {
  it("resolves HM_ARCH_HOME override", () => {
    const home = resolveHmArchHome({ envHome: "/tmp/hm-arch-test-home" });
    assert.equal(home, "/tmp/hm-arch-test-home");
    assert.equal(managedEnvRoot(home), "/tmp/hm-arch-test-home/python-env");
  });

  it("places managed python under python-env", () => {
    const home = "/tmp/example";
    const python = managedPythonExecutable(home);
    if (process.platform === "win32") {
      assert.match(python, /python-env[\\/]Scripts[\\/]python\.exe$/);
    } else {
      assert.equal(python, "/tmp/example/python-env/bin/python");
    }
  });

  it("places managed hm-arch console script under python-env", () => {
    const home = "/tmp/example";
    const cli = managedHmArchExecutable(home);
    if (process.platform === "win32") {
      assert.match(cli, /python-env[\\/]Scripts[\\/]hm-arch\.exe$/);
    } else {
      assert.equal(cli, "/tmp/example/python-env/bin/hm-arch");
    }
  });
});
