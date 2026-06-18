import {
  buildJsonPluginConfigSchema,
  definePluginEntry,
  type OpenClawPluginApi,
  type OpenClawPluginDefinition,
} from "openclaw/plugin-sdk/plugin-entry";

import { HM_ARCH_PLUGIN_ID, pluginConfigSchema, resolvePluginConfig } from "./config.js";
import { runAgentEnd, runBeforePromptBuild, runSessionEnd } from "./hooks.js";
import type { AutoCaptureCursor } from "./messages.js";
import { hasMemorySlotConflict, isActiveMemoryPlugin } from "./slot.js";
import { SidecarManager } from "./sidecar-manager.js";
import { createMemoryTools } from "./tools.js";

const plugin: OpenClawPluginDefinition = definePluginEntry({
  id: HM_ARCH_PLUGIN_ID,
  name: "HM-Arch Memory",
  description: "HM-Arch local SQLite memory provider for OpenClaw",
  kind: "memory",
  configSchema: () => buildJsonPluginConfigSchema(pluginConfigSchema()),
  register(api: OpenClawPluginApi) {
    if (hasMemorySlotConflict(api.config)) {
      api.logger.warn(
        `memory-hm-arch: plugins.slots.memory is not '${HM_ARCH_PLUGIN_ID}'; skipping memory registration`,
      );
      return;
    }
    if (!isActiveMemoryPlugin(api.config)) {
      api.logger.warn(
        `memory-hm-arch: memory slot is not configured for '${HM_ARCH_PLUGIN_ID}'; plugin loaded but inactive`,
      );
    }

    const captureCursors = new Map<string, AutoCaptureCursor>();
    const resolveConfig = () =>
      resolvePluginConfig(api.pluginConfig, (input) => api.resolvePath(input));

    const sidecarHolder: { current: SidecarManager } = {
      current: new SidecarManager({
        command: resolveConfig().sidecarCommand,
        dbPath: resolveConfig().dbPath,
        requestTimeoutMs: resolveConfig().requestTimeoutMs,
        startupTimeoutMs: resolveConfig().startupTimeoutMs,
        maxRestartBackoffMs: resolveConfig().maxRestartBackoffMs,
        logger: api.logger,
      }),
    };

    const refreshSidecar = () => {
      const config = resolveConfig();
      sidecarHolder.current = new SidecarManager({
        command: config.sidecarCommand,
        dbPath: config.dbPath,
        requestTimeoutMs: config.requestTimeoutMs,
        startupTimeoutMs: config.startupTimeoutMs,
        maxRestartBackoffMs: config.maxRestartBackoffMs,
        logger: api.logger,
      });
    };

    for (const tool of createMemoryTools({
      getConfig: resolveConfig,
      get sidecar() {
        return sidecarHolder.current;
      },
      logger: api.logger,
    })) {
      api.registerTool(tool, { name: tool.name });
    }

    api.registerService({
      id: "memory-hm-arch-sidecar",
      start: async () => {
        refreshSidecar();
        try {
          await sidecarHolder.current.start();
          api.logger.info?.(`memory-hm-arch: sidecar started for ${resolveConfig().dbPath}`);
        } catch (error) {
          api.logger.warn?.(
            `memory-hm-arch: sidecar failed to start (fail-open): ${String(error)}`,
          );
        }
      },
      stop: async () => {
        try {
          await sidecarHolder.current.stop();
        } catch (error) {
          api.logger.warn?.(`memory-hm-arch: sidecar stop failed: ${String(error)}`);
        }
      },
    });

    api.on(
      "before_prompt_build",
      async (event) =>
        await runBeforePromptBuild(
          {
            config: resolveConfig(),
            sidecar: sidecarHolder.current,
            logger: api.logger,
            captureCursors,
          },
          event,
        ),
      { timeoutMs: resolveConfig().requestTimeoutMs },
    );

    api.on(
      "agent_end",
      async (event, ctx) => {
        await runAgentEnd(
          {
            config: resolveConfig(),
            sidecar: sidecarHolder.current,
            logger: api.logger,
            captureCursors,
          },
          event,
          {
            sessionId: ctx.sessionId,
            sessionKey: ctx.sessionKey,
          },
        );
      },
      { timeoutMs: resolveConfig().requestTimeoutMs },
    );

    api.on(
      "session_end",
      async (event, ctx) => {
        await runSessionEnd(
          {
            config: resolveConfig(),
            sidecar: sidecarHolder.current,
            logger: api.logger,
            captureCursors,
          },
          event,
          {
            sessionId: ctx.sessionId,
            sessionKey: ctx.sessionKey,
          },
        );
      },
      { timeoutMs: resolveConfig().requestTimeoutMs },
    );
  },
});

export default plugin;
