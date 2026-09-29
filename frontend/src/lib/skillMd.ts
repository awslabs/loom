/** Parsing/building helpers for SKILL.md content.
 *
 * The frontmatter schema Loom writes (and AWS's registry validates) is small
 * and fixed — {name, description, license, metadata: {author, version}} —
 * so this is a purpose-built parser for that shape, not a general YAML
 * parser. Keeping the fields and the frontmatter in sync (rather than
 * letting an author hand-edit YAML that can disagree with the fields) is
 * the whole point: buildSkillMd is the only thing that ever writes the
 * frontmatter block.
 */

export interface SkillFrontmatter {
  name: string;
  description: string;
  license: string;
  author: string;
  version: string;
}

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;

function stripQuotes(raw: string): string {
  const t = raw.trim();
  if (t.length >= 2 && ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'")))) {
    return t.slice(1, -1);
  }
  return t;
}

/** Split a SKILL.md file into its frontmatter fields and body. Fields not
 * present in the frontmatter are simply absent from the returned object —
 * callers should fall back to other sources (e.g. the registry record's
 * top-level name/description) for those. */
export function parseSkillMd(md: string): { frontmatter: Partial<SkillFrontmatter>; body: string } {
  const match = FRONTMATTER_RE.exec(md);
  if (!match) return { frontmatter: {}, body: md };
  const yamlBlock = match[1] ?? "";
  const rest = match[2] ?? "";
  const frontmatter: Partial<SkillFrontmatter> = {};
  let inMetadata = false;
  for (const line of yamlBlock.split(/\r?\n/)) {
    if (/^metadata:\s*$/.test(line)) {
      inMetadata = true;
      continue;
    }
    const indented = /^\s+(\w+):\s*(.*)$/.exec(line);
    if (inMetadata && indented) {
      const key = indented[1];
      const value = stripQuotes(indented[2] ?? "");
      if (key === "author") frontmatter.author = value;
      if (key === "version") frontmatter.version = value;
      continue;
    }
    inMetadata = false;
    const topLevel = /^(\w+):\s*(.*)$/.exec(line);
    if (topLevel) {
      const key = topLevel[1];
      const value = stripQuotes(topLevel[2] ?? "");
      if (key === "name") frontmatter.name = value;
      if (key === "description") frontmatter.description = value;
      if (key === "license") frontmatter.license = value;
    }
  }
  return { frontmatter, body: rest.replace(/^\r?\n/, "") };
}

/** Serialize frontmatter + body into a full SKILL.md file. The only place a
 * frontmatter block is ever generated — the editor never lets a user type
 * YAML by hand, so the fields and the file can't disagree. */
export function buildSkillMd(frontmatter: SkillFrontmatter, body: string): string {
  const yaml = [
    "---",
    `name: ${frontmatter.name}`,
    `description: ${frontmatter.description}`,
    `license: ${frontmatter.license}`,
    "metadata:",
    `  author: ${frontmatter.author}`,
    `  version: "${frontmatter.version}"`,
    "---",
    "",
  ].join("\n");
  return yaml + body;
}

/** Pull a named "## Heading" section's bullet list items out of a markdown
 * body, returning the items and the body with that section removed (so the
 * caller can render the rest normally and the bullets separately, e.g. as
 * chips for "## Prerequisites"). Case-insensitive heading match; matches
 * simple "- item" or "* item" bullets only. */
export function extractBulletSection(body: string, heading: string): { items: string[]; remainingBody: string } {
  const re = new RegExp(`(^|\\n)##\\s+${heading}\\s*\\n([\\s\\S]*?)(?=\\n##\\s|$)`, "i");
  const match = re.exec(body);
  if (!match) return { items: [], remainingBody: body };
  const full = match[0];
  const sectionBody = match[2] ?? "";
  const items = sectionBody
    .split("\n")
    .map((l) => /^\s*[-*]\s+(.*)$/.exec(l)?.[1]?.trim())
    .filter((s): s is string => Boolean(s));
  const remainingBody = body.slice(0, match.index) + body.slice(match.index + full.length);
  return { items, remainingBody };
}

/** Count numbered list items across a markdown body — used for the "N
 * steps" chip on the skill list card. Counts top-level "1. " / "2. "
 * style lines, not nested sub-lists. */
export function countSteps(body: string): number {
  const matches = body.match(/^\d+\.\s+/gm);
  return matches ? matches.length : 0;
}

/** True if a paragraph of text is an "IMPORTANT: ..." callout, with or
 * without surrounding markdown bold markers. */
export function isImportantCallout(text: string): boolean {
  return /^\*{0,2}IMPORTANT[:.]?/i.test(text.trim());
}

/** Suggest the next patch version for the "Publish vX.Y.Z" button — a
 * starting point only, always editable by the author (never auto-applied
 * without their say). Falls back to "1.0.0" for an unparseable/absent
 * current version. */
export function suggestNextVersion(current: string | undefined): string {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec((current ?? "").trim());
  if (!match) return "1.0.0";
  const major = match[1];
  const minor = match[2];
  const patch = Number(match[3]);
  return `${major}.${minor}.${patch + 1}`;
}
