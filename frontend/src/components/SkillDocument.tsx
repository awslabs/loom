import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { AlertTriangle } from "lucide-react";
import { extractBulletSection } from "@/lib/skillMd";

/** Flatten React children (strings and nested elements, e.g. the <strong>
 * markdown produces for **bold** text) into plain text, so callers can
 * pattern-match on a rendered paragraph's actual content. */
function childrenToText(children: ReactNode): string {
  if (children == null || typeof children === "boolean") return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  if (typeof children === "object" && "props" in children) {
    return childrenToText((children as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

interface SkillDocumentProps {
  /** The SKILL.md body (frontmatter already stripped). */
  body: string;
  className?: string;
}

/** Renders a skill's markdown body as a document, the same way for the
 * detail page's "rendered" view and the editor's live preview:
 * - a paragraph starting with "IMPORTANT" renders as a warning callout
 * - a "## Prerequisites" section's bullets render as chips instead of a list
 * - ordered lists render with their native numbering, lightly styled
 * - everything else falls back to normal prose markdown
 */
export function SkillDocument({ body, className }: SkillDocumentProps) {
  const { items: prerequisites, remainingBody } = extractBulletSection(body, "Prerequisites");

  return (
    <div className={className}>
      <div className="prose prose-sm dark:prose-invert max-w-none [&_ol]:rounded-lg [&_ol]:border [&_ol]:divide-y [&_ol]:list-decimal [&_ol]:pl-9 [&_ol]:marker:font-mono [&_ol]:marker:text-xs [&_ol]:marker:text-muted-foreground [&_li]:py-2 [&_li]:pr-3">
        <ReactMarkdown
          components={{
            p: ({ children, ...props }) => {
              const text = childrenToText(children);
              if (/^\*{0,2}IMPORTANT[:.]?/i.test(text.trim())) {
                return (
                  <div className="not-prose flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-bg px-3 py-2.5 my-3">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-warning" aria-hidden />
                    <span className="text-xs leading-relaxed text-warning">{text.replace(/^IMPORTANT[:.]?\s*/i, "")}</span>
                  </div>
                );
              }
              return <p {...props}>{children}</p>;
            },
          }}
        >
          {remainingBody}
        </ReactMarkdown>
      </div>

      {prerequisites.length > 0 && (
        <div className="mt-5 flex flex-col gap-2">
          <div className="text-sm font-semibold">Prerequisites</div>
          <div className="flex flex-wrap gap-1.5">
            {prerequisites.map((item) => (
              <span key={item} className="font-mono text-[11px] px-2 py-1 rounded-md bg-muted border">{item}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
