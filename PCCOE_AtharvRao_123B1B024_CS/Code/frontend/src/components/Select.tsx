import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

export interface Option {
  value: string;
  label: string;
  /** Smaller second line, e.g. an entity type. */
  hint?: string;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
  /** Visible label, rendered above the control. */
  label?: string;
  /** Show a search box when there are more options than this. */
  searchableAbove?: number;
  className?: string;
}

/**
 * A styled dropdown with search and keyboard support (arrows, Enter, Escape, type to filter).
 * Replaces the browser's native list so long entity lists stay usable.
 */
export function Select({ value, onChange, options, placeholder = "Select…", disabled, label, searchableAbove = 8, className }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const listId = useId();
  const searchable = options.length > searchableAbove;

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((option) => `${option.label} ${option.hint ?? ""}`.toLowerCase().includes(needle)) : options;
  }, [options, query]);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(Math.max(0, options.findIndex((option) => option.value === value)));
      if (searchable) window.setTimeout(() => search.current?.focus(), 0);
    }
  }, [open, options, value, searchable]);

  function choose(option: Option) {
    onChange(option.value);
    setOpen(false);
  }

  function onKey(event: KeyboardEvent) {
    if (disabled) return;
    if (!open && (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (event.key === "Escape") setOpen(false);
    else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(shown.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (shown[active]) choose(shown[active]);
    }
  }

  const control = (
    <div className={`select ${open ? "select-open" : ""} ${disabled ? "select-disabled" : ""} ${className ?? ""}`} ref={root} onKeyDown={onKey} onClick={(event) => event.preventDefault() /* inside a <label>: do not forward the click */}>
      <button
        type="button"
        className="select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={selected ? "" : "select-placeholder"}>
          {selected ? selected.label : placeholder}
          {selected?.hint && <small className="select-hint"> {selected.hint}</small>}
        </span>
        <span className="select-chevron" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="select-panel">
          {searchable && (
            <input
              ref={search}
              className="select-search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActive(0);
              }}
              placeholder="Type to filter…"
              aria-label="Filter options"
            />
          )}
          <ul id={listId} role="listbox" className="select-list">
            {shown.length === 0 && <li className="select-empty">No matches</li>}
            {shown.map((option, index) => (
              <li
                key={option.value}
                role="option"
                aria-selected={option.value === value}
                className={`select-option ${index === active ? "select-active" : ""} ${option.value === value ? "select-chosen" : ""}`}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(option);
                }}
              >
                <span>{option.label}</span>
                {option.hint && <small>{option.hint}</small>}
                {option.value === value && <span className="select-tick" aria-hidden="true">✓</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );

  return label ? (
    <div className="field">
      <span className="field-label">{label}</span>
      {control}
    </div>
  ) : (
    control
  );
}
