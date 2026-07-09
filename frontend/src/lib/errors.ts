/**
 * Maps raw invoke error messages to user-friendly messages.
 * Returns the friendly message, or the original if no pattern matches.
 *
 * @param authorizerName - Optional authorizer name from the agent's config,
 *   used to suggest the correct credential on 403 errors.
 */
export function friendlyInvokeError(raw: string, authorizerName?: string): string {
  const lower = raw.toLowerCase();

  // HTTP 401 or unauthorized
  if (lower.includes("401") || lower.includes("unauthorized")) {
    const hint = authorizerName
      ? ` This agent uses the "${authorizerName}" authorizer — select a credential from that authorizer.`
      : "";
    return `This agent requires authentication. Please select a credential or provide a bearer token in the Invoke panel before sending a prompt.${hint}`;
  }

  // HTTP 403 or forbidden/access denied
  if (lower.includes("403") || lower.includes("forbidden") || lower.includes("access denied") || lower.includes("accessdenied")) {
    const hint = authorizerName
      ? ` This agent uses the "${authorizerName}" authorizer — make sure you select a credential from that authorizer.`
      : "";
    return `Access was denied. The selected credential may not have the required permissions for this agent.${hint}`;
  }

  // Token errors
  if (lower.includes("token") && (lower.includes("failed") || lower.includes("error") || lower.includes("expired"))) {
    return "The credential token could not be obtained or has expired. Please verify the credential configuration in the Security Admin page and try again.";
  }

  // Missing credential
  if (lower.includes("no credential") || lower.includes("credential not found") || lower.includes("credential_id")) {
    return "A credential is required to invoke this agent. Please select one from the credential dropdown in the Invoke panel.";
  }

  // No match — return original
  return raw;
}
