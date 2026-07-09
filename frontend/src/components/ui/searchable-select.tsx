import { useState, useRef, useEffect } from "react";
import { ChevronDownIcon, CheckIcon, SearchIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchableSelectOption {
  value: string;
  label: string;
  group?: string;
}

interface SearchableSelectProps {
  options: SearchableSelectOption[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export function SearchableSelect({
  options,
  value,
  onValueChange,
  placeholder = "Select...",
  className,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = options.filter((o) => {
    const q = search.toLowerCase();
    return o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q);
  });

  const selectedLabel = options.find((o) => o.value === value)?.label;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-input-bg px-3 py-2 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 hover:bg-input-bg/80"
      >
        <span className={cn("truncate", !selectedLabel && "text-muted-foreground")}>
          {selectedLabel ?? placeholder}
        </span>
        <ChevronDownIcon className="size-4 shrink-0 opacity-50" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[8rem] rounded-md border bg-input-bg text-popover-foreground shadow-md">
          <div className="flex items-center gap-2 border-b px-2 py-1.5">
            <SearchIcon className="size-3.5 text-muted-foreground shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search..."
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="max-h-48 overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">No results</div>
            ) : (
              (() => {
                const hasGroups = filtered.some((o) => o.group);
                if (!hasGroups) {
                  return filtered.map((o) => (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => {
                        onValueChange(o.value);
                        setOpen(false);
                        setSearch("");
                      }}
                      className="relative flex w-full cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none hover:bg-accent hover:text-accent-foreground"
                    >
                      <span className="truncate">{o.label}</span>
                      {o.value === value && (
                        <span className="absolute right-2 flex size-3.5 items-center justify-center">
                          <CheckIcon className="size-4" />
                        </span>
                      )}
                    </button>
                  ));
                }
                const groups: string[] = [];
                for (const o of filtered) {
                  const g = o.group ?? "";
                  if (!groups.includes(g)) groups.push(g);
                }
                return groups.map((g) => (
                  <div key={g}>
                    {g && (
                      <div className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                        {g}
                      </div>
                    )}
                    {filtered
                      .filter((o) => (o.group ?? "") === g)
                      .map((o) => (
                        <button
                          key={o.value}
                          type="button"
                          onClick={() => {
                            onValueChange(o.value);
                            setOpen(false);
                            setSearch("");
                          }}
                          className="relative flex w-full cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none hover:bg-accent hover:text-accent-foreground"
                        >
                          <span className="truncate">{o.label}</span>
                          {o.value === value && (
                            <span className="absolute right-2 flex size-3.5 items-center justify-center">
                              <CheckIcon className="size-4" />
                            </span>
                          )}
                        </button>
                      ))}
                  </div>
                ));
              })()
            )}
          </div>
        </div>
      )}
    </div>
  );
}
