import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell } from "lucide-react";
import { api, getToken } from "../api";
import { Badge, Button, cn } from "./ui";

type AlertItem = {
  id: number;
  marketplace: string;
  chat_id: string;
  email: string | null;
  cnt_new: number;
  last_message_at: string | null;
  order_id: number | null;
  customer_id: number | null;
};

type AlertsResponse = { total_new: number; items: AlertItem[] };

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<AlertsResponse>({ total_new: 0, items: [] });
  const rootRef = useRef<HTMLDivElement>(null);
  const nav = useNavigate();

  async function load() {
    if (!getToken()) return;
    try {
      setData(await api<AlertsResponse>("/store/api/messages/alerts"));
    } catch {
      /* keep previous snapshot */
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(load, 45_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!open) return;
    load();
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function openAlert(item: AlertItem) {
    setOpen(false);
    if (item.customer_id != null) nav(`/inbox?customer=${item.customer_id}`);
    else nav("/inbox");
  }

  return (
    <div ref={rootRef} className="relative">
      <Button
        className="relative h-10 w-10 px-0"
        aria-label="Inbox notifications"
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="h-4 w-4" />
        {data.total_new > 0 && (
          <span className="absolute -right-1 -top-1 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
            {data.total_new > 99 ? "99+" : data.total_new}
          </span>
        )}
      </Button>
      {open && (
        <div className="absolute right-0 top-12 z-50 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-lg border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-medium">Inbox</span>
            <span className="text-xs text-muted-foreground">{data.total_new} unread</span>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {data.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "flex w-full flex-col gap-1 border-b border-white/5 px-3 py-2.5 text-left hover:bg-white/5",
                )}
                onClick={() => openAlert(item)}
              >
                <div className="flex items-center gap-2">
                  <Badge>{item.marketplace}</Badge>
                  <span className="text-xs text-muted-foreground">{item.cnt_new} new</span>
                </div>
                <div className="truncate text-sm">
                  {item.email || (item.customer_id != null ? `Customer #${item.customer_id}` : `Chat ${item.chat_id}`)}
                </div>
                {item.last_message_at && (
                  <div className="text-[11px] text-muted-foreground">
                    {new Date(item.last_message_at).toLocaleString()}
                  </div>
                )}
              </button>
            ))}
            {!data.items.length && (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">No unread chats</p>
            )}
          </div>
          <button
            type="button"
            className="block w-full border-t px-3 py-2 text-center text-xs text-muted-foreground hover:bg-white/5 hover:text-foreground"
            onClick={() => { setOpen(false); nav("/inbox"); }}
          >
            Open Inbox
          </button>
        </div>
      )}
    </div>
  );
}
