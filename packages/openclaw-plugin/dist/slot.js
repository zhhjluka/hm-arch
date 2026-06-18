import { HM_ARCH_PLUGIN_ID } from "./config.js";
const EMPTY_SLOT_VALUES = new Set(["", "none"]);
export function readConfiguredMemorySlot(config) {
    const plugins = config.plugins;
    if (!plugins || typeof plugins !== "object") {
        return undefined;
    }
    const slots = plugins.slots;
    if (!slots || typeof slots !== "object") {
        return undefined;
    }
    const memory = slots.memory;
    if (typeof memory !== "string") {
        return undefined;
    }
    const trimmed = memory.trim();
    if (!trimmed || EMPTY_SLOT_VALUES.has(trimmed.toLowerCase())) {
        return undefined;
    }
    return trimmed;
}
export function hasMemorySlotConflict(config) {
    const configured = readConfiguredMemorySlot(config);
    if (!configured) {
        return false;
    }
    return configured !== HM_ARCH_PLUGIN_ID;
}
export function isActiveMemoryPlugin(config) {
    const configured = readConfiguredMemorySlot(config);
    return configured === HM_ARCH_PLUGIN_ID;
}
//# sourceMappingURL=slot.js.map