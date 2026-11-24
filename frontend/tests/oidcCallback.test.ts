// Run with `npm test` (node:test + Node's built-in TypeScript type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";

import { checkOIDCCallback } from "../src/lib/oidcCallback.ts";

const STATE = "0123456789abcdef0123456789abcdef";
const VERIFIER = "v".repeat(64);

test("accepts a callback whose state matches the pending sign-in", () => {
  assert.deepEqual(checkOIDCCallback(STATE, STATE, VERIFIER), { ok: true, codeVerifier: VERIFIER });
});

test("rejects a callback when no sign-in was started in this tab", () => {
  assert.equal(checkOIDCCallback(STATE, null, null).ok, false);
  assert.equal(checkOIDCCallback(null, null, null).ok, false);
});

test("rejects a callback without a state parameter", () => {
  assert.equal(checkOIDCCallback(null, STATE, VERIFIER).ok, false);
  assert.equal(checkOIDCCallback("", STATE, VERIFIER).ok, false);
});

test("rejects a callback whose state does not match", () => {
  assert.equal(checkOIDCCallback("attacker-state", STATE, VERIFIER).ok, false);
});

test("rejects a matching state when the PKCE verifier is gone", () => {
  assert.equal(checkOIDCCallback(STATE, STATE, null).ok, false);
  assert.equal(checkOIDCCallback(STATE, STATE, "").ok, false);
});

test("rejects an empty stored state even if the callback has none either", () => {
  assert.equal(checkOIDCCallback("", "", VERIFIER).ok, false);
});
