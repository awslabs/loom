import { useState, useRef, useEffect } from "react";
import { Plus, ChevronDown } from "lucide-react";

interface AddFilterDropdownProps {
  options: { key: string; label: string }[];
  onSelect: (key: string) => void;
}

export function AddFilterDropdown({ options, onSelect }: AddFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-7 min-w-[140px] items-center justify-between rounded-md border border-input bg-input-bg px-2 text-xs shadow-xs hover:bg-input-bg/80"
      >
        <span className="flex items-center gap-1">
          <Plus className="h-3 w-3" />
          Add filter
        </span>
        <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 min-w-full w-max rounded-md border bg-input-bg p-1 shadow-md">
          {options.map((opt) => (
            <button
              key={opt.key}
              type="button"
              className="flex w-full items-center rounded-sm px-2 py-1 text-xs cursor-pointer hover:bg-accent whitespace-nowrap text-left"
              onClick={() => {
                onSelect(opt.key);
                setOpen(false);
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
