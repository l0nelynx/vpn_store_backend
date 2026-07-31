import { useEffect, useState, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";

export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn("button", className)} {...props} />;
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("field", className)} {...props} />;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "sync";
}) {
  const tones = {
    neutral: "bg-white/5",
    success: "border-success/30 bg-success/10 text-success",
    warning: "border-warning/30 bg-warning/10 text-warning",
    danger: "border-danger/30 bg-danger/10 text-danger",
    sync: "border-sync/30 bg-sync/10 text-sync",
  };
  return <span className={cn("badge", tones[tone])}>{children}</span>;
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="grid min-h-48 place-items-center rounded-lg border border-dashed p-8 text-center">
      <div>
        <p className="font-medium">{title}</p>
        <p className="muted mt-1">{detail}</p>
      </div>
    </div>
  );
}

/** Desktop table + mobile card list switch. */
export function DataList({
  table,
  cards,
  className,
}: {
  table: ReactNode;
  cards: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="hidden md:block">{table}</div>
      <div className="space-y-2 md:hidden">{cards}</div>
    </div>
  );
}

/** Expandable list card for hybrid mobile tables. */
export function ListCard({
  title,
  subtitle,
  badges,
  details,
  actions,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  onClick,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  badges?: ReactNode;
  details?: ReactNode;
  actions?: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onClick?: () => void;
}) {
  const [internal, setInternal] = useState(defaultOpen);
  const expanded = controlledOpen ?? internal;
  const setExpanded = (v: boolean) => {
    if (controlledOpen === undefined) setInternal(v);
    onOpenChange?.(v);
  };
  const expandable = details != null || actions != null;

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex w-full items-start gap-1 p-3">
        <button
          type="button"
          className="min-w-0 flex-1 text-left"
          onClick={() => {
            if (onClick) onClick();
            else if (expandable) setExpanded(!expanded);
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-sm font-medium">{title}</div>
            {badges}
          </div>
          {subtitle != null && <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>}
        </button>
        {expandable && (
          <button
            type="button"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-white/8"
            aria-label={expanded ? "Collapse" : "Expand"}
            onClick={() => setExpanded(!expanded)}
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} />
          </button>
        )}
      </div>
      {expandable && expanded && (
        <div className="space-y-3 border-t px-3 py-3 text-sm">
          {details}
          {actions && <div className="flex flex-wrap gap-2 pt-1">{actions}</div>}
        </div>
      )}
    </div>
  );
}

export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="min-w-0 flex-1 break-words">{children}</div>
    </div>
  );
}

/** Full-screen / side overlay for master-detail on narrow viewports. */
export function Sheet({
  open,
  onClose,
  title,
  children,
  wide = false,
  until = "md",
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  wide?: boolean;
  /** Hide the sheet at this breakpoint and above (desktop panel takes over). */
  until?: "md" | "lg" | "xl";
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const hideAt = until === "xl" ? "xl:hidden" : until === "lg" ? "lg:hidden" : "md:hidden";

  return (
    <div className={cn("fixed inset-0 z-50 flex justify-end", hideAt)}>
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div
        className={cn(
          "relative flex h-full w-full flex-col border-l bg-background shadow-xl",
          wide ? "max-w-full" : "max-w-lg",
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
          <Button className="h-10 w-10 px-0" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
          {title != null && <div className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</div>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">{children}</div>
      </div>
    </div>
  );
}
