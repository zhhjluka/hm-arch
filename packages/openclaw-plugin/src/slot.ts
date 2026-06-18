import type { OpenClawConfig } from "openclaw/plugin-sdk/plugin-entry";

import { HM_ARCH_PLUGIN_ID } from "./config.js";

const EMPTY_SLOT_VALUES = new Set(["", "none"]);

export function readConfiguredMemorySlot(config: OpenClawConfig): string | undefined {
  const plugins = config.plugins;
  if (!plugins || typeof plugins !== "object") {
    return undefined;
  }
  const slots = (plugins as { slots?: unknown }).slots;
  if (!slots || typeof slots !== "object") {
    return undefined;
  }
  const memory = (slots as { memory?: unknown }).memory;
  if (typeof memory !== "string") {
    return undefined;
  }
  const trimmed = memory.trim();
  if (!trimmed || EMPTY_SLOT_VALUES.has(trimmed.toLowerCase())) {
    return undefined;
  }
  return trimmed;
}

export function hasMemorySlotConflict(config: OpenClawConfig): boolean {
  const configured = readConfiguredMemorySlot(config);
  if (!configured) {
    return false;
  }
  return configured !== HM_ARCH_PLUGIN_ID;
}

export function isActiveMemoryPlugin(config: OpenClawConfig): boolean {
  const configured = readConfiguredMemorySlot(config);
  return configured === HM_ARCH_PLUGIN_ID;
}
