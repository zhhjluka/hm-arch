import assert from "node:assert/strict";
import path from "node:path";
import { describe, it } from "node:test";

import {
  managedEnvRoot,
  managedHmArchExecutable,
  managedPythonExecutable,
  managedStandaloneExecutable,
  resolveHmArchHome,
  standaloneBinaryRoot,
} from "../src/paths.js";

describe("paths", () => {
  it("resolves HM_ARCH_HOME override", () => {
    const envHome = path.join(path.parse(process.cwd()).root, "tmp", "hm-arch-test-home");
    const home = resolveHmArchHome({ envHome });
    assert.equal(home, path.resolve(envHome));
    assert.equal(managedEnvRoot(home), path.join(path.resolve(envHome), "python-env"));
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

  it("places standalone hm-arch binary under standalone/", () => {
    const home = "/tmp/example";
    const root = standaloneBinaryRoot(home);
    const cli = managedStandaloneExecutable(home);
    if (process.platform === "win32") {
      assert.equal(root, "/tmp/example/standalone");
      assert.match(cli, /standalone[\\/]hm-arch\.exe$/);
    } else {
      assert.equal(root, "/tmp/example/standalone");
      assert.equal(cli, "/tmp/example/standalone/hm-arch");
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
