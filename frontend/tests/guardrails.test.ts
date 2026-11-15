// Run with `npm test` (node:test + Node's built-in TypeScript type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  guardrailSelectionOptions,
  hasUsableDefault,
  initialGuardrailSelection,
} from "../src/lib/guardrails.ts";
import type { GuardrailDefault } from "../src/api/types.ts";

const config = {
  guardrail_id: "abc123",
  guardrail_version: "1",
  mode: "enforce",
  stream_processing_mode: "sync",
  redact_history: true,
  allowed: [],
} as unknown as NonNullable<GuardrailDefault["config"]>;

const def = (over: Partial<GuardrailDefault>): GuardrailDefault =>
  ({ enabled: false, locked: false, config: null, source: "none", ...over }) as GuardrailDefault;

const NONE_SET = def({});
const SET = def({ enabled: true, config, source: "settings" });
const LOCKED = def({ enabled: true, locked: true, config, source: "settings" });
const ENABLED_NO_CONFIG = def({ enabled: true });

test("hasUsableDefault needs enabled and a guardrail", () => {
  assert.equal(hasUsableDefault(null), false);
  assert.equal(hasUsableDefault(NONE_SET), false);
  assert.equal(hasUsableDefault(ENABLED_NO_CONFIG), false);
  assert.equal(hasUsableDefault(def({ config })), false); // configured but disabled
  assert.equal(hasUsableDefault(SET), true);
});

test("new agents start on none when no default exists, inherit when one does", () => {
  assert.equal(initialGuardrailSelection(null), null); // still loading / unreadable: leave alone
  assert.equal(initialGuardrailSelection(NONE_SET), "none");
  assert.equal(initialGuardrailSelection(SET), "default");
  assert.equal(initialGuardrailSelection(LOCKED), "default");
});

test("inherit is disabled without a default, unless it's the agent's saved choice", () => {
  assert.equal(guardrailSelectionOptions(NONE_SET, "none").inheritDisabled, true);
  assert.equal(guardrailSelectionOptions(NONE_SET, "custom").inheritDisabled, true);
  assert.ok(guardrailSelectionOptions(NONE_SET, "none").inheritTitle);
  assert.equal(guardrailSelectionOptions(NONE_SET, "default").inheritDisabled, false);
  assert.equal(guardrailSelectionOptions(SET, "none").inheritDisabled, false);
  assert.equal(guardrailSelectionOptions(SET, "none").inheritTitle, undefined);
});

test("unknown default disables nothing", () => {
  const opts = guardrailSelectionOptions(null, "default");
  assert.equal(opts.inheritDisabled, false);
  assert.equal(opts.showNone, true);
});

test("none is hidden under a locked default, unless already selected", () => {
  assert.equal(guardrailSelectionOptions(LOCKED, "default").showNone, false);
  assert.equal(guardrailSelectionOptions(LOCKED, "custom").showNone, false);
  assert.equal(guardrailSelectionOptions(LOCKED, "none").showNone, true);
  assert.equal(guardrailSelectionOptions(SET, "default").showNone, true);
  assert.equal(guardrailSelectionOptions(NONE_SET, "default").showNone, true);
});
