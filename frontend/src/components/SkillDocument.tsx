import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { AlertTriangle } from "lucide-react";
import { extractBulletSection } from "@/lib/skillMd";

/** Flatten React children (strings and nested elements, e.g. the <strong>
 * markdown produces for **bold** text) into plain text, so callers can
 * pattern-match on or split a rendered node's actual content. */
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

/** Renders a skill's markdown body as a tight, document-style layout —
 * matching the Claude Design "Loom Skills" mockup's spacing/type scale
 * rather than a generic prose article:
 * - a paragraph starting with "IMPORTANT" renders as a warning callout
 * - a "## Prerequisites" section's bullets render as chips instead of a list
 * - other bullet lists render with an en-dash, not a browser marker
 * - ordered lists render as a 3-col step table (number · name · detail),
 *   splitting each "**Name** — detail" item on its first dash
 * - everything is spaced with explicit gaps (no prose margins), since the
 *   typography plugin's defaults read as noticeably airier than the mockup
 */
export function SkillDocument({ body, className }: SkillDocumentProps) {
  const { items: prerequisites, remainingBody } = extractBulletSection(body, "Prerequisites");

  return (
    <div className={`flex flex-col gap-3.5 text-sm ${className ?? ""}`}>
      <ReactMarkdown
        components={{
          h1: ({ children }) => <div className="text-[20px] font-semibold tracking-tight leading-snug">{children}</div>,
          h2: ({ children }) => <div className="text-[14.5px] font-semibold mt-1">{children}</div>,
          h3: ({ children }) => <div className="text-[13.5px] font-semibold">{children}</div>,
          p: ({ children }) => {
            const text = childrenToText(children);
            if (/^\*{0,2}IMPORTANT[:.]?/i.test(text.trim())) {
              return (
                <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-bg px-3 py-2">
                  <AlertTriangle className="h-3 w-3 shrink-0 text-warning" aria-hidden />
                  <span className="text-[12.5px] leading-snug text-warning">{text.replace(/^\*{0,2}IMPORTANT[:.]?\s*/i, "")}</span>
                </div>
              );
            }
            return <p className="text-[13.5px] leading-[1.6]">{children}</p>;
          },
          ul: ({ children }) => (
            <div className="flex flex-col gap-1">
              {Children.toArray(children).map((child, i) => {
                if (!isValidElement(child)) return null;
                const text = childrenToText((child.props as { children?: ReactNode }).children);
                return (
                  <div key={i} className="flex gap-2 text-[13.5px] leading-[1.6]">
                    <span className="text-muted-foreground shrink-0">–</span>
                    <span>{text}</span>
                  </div>
                );
              })}
            </div>
          ),
          ol: ({ children }) => (
            <div className="flex flex-col border rounded-lg overflow-hidden">
              {Children.toArray(children).map((child, i) => {
                if (!isValidElement(child)) return null;
                const raw = childrenToText((child.props as { children?: ReactNode }).children);
                const match = /^(.*?)\s*[-–]\s*(.*)$/.exec(raw);
                const name = match ? match[1] : raw;
                const detail = match ? match[2] : "";
                return (
                  <div
                    key={i}
                    className={`grid grid-cols-[28px_170px_minmax(0,1fr)] gap-2.5 px-3.5 py-2 items-baseline ${i > 0 ? "border-t" : ""}`}
                  >
                    <span className="font-mono text-[11px] text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                    <span className="text-[13px] font-medium">{name}</span>
                    <span className="text-[12.5px] text-muted-foreground">{detail}</span>
                  </div>
                );
              })}
            </div>
          ),
        }}
      >
        {remainingBody}
      </ReactMarkdown>

      {prerequisites.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[14.5px] font-semibold">Prerequisites</div>
          <div className="flex flex-wrap gap-1.5">
            {prerequisites.map((item) => (
              <span key={item} className="font-mono text-[11.5px] px-2 py-0.5 rounded-md bg-muted border">{item}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
