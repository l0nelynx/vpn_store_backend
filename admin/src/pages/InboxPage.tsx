import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Button, Card, Empty, Sheet } from "../components/ui";

type Thread = {
  customer_id: number;
  email: string | null;
  order_count: number;
  last_message: string | null;
  last_at: string | null;
};

type Msg = {
  id: number;
  direction: string;
  body: string | null;
  marketplace: string;
  order_id: number | null;
  written_at: string | null;
};

type Order = {
  id: number;
  marketplace: string;
  external_order_id: string;
};

const PAGE_SIZE = 20;

export default function InboxPage() {
  const [params] = useSearchParams();
  const initialCustomer = params.get("customer");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [q, setQ] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [sort, setSort] = useState("last_at");
  const [orderDir, setOrderDir] = useState("desc");
  const [customerId, setCustomerId] = useState<number | null>(
    initialCustomer ? Number(initialCustomer) : null,
  );
  const [messages, setMessages] = useState<Msg[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [orderId, setOrderId] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sheetOpen, setSheetOpen] = useState(!!initialCustomer);

  async function loadThreads(p = page) {
    const offset = p * PAGE_SIZE;
    const qs = new URLSearchParams();
    qs.set("limit", String(PAGE_SIZE));
    qs.set("offset", String(offset));
    if (q.trim()) qs.set("q", q.trim());
    if (marketplace) qs.set("marketplace", marketplace);
    qs.set("sort", sort);
    qs.set("order", orderDir);
    const res = await api<{ items: Thread[]; total: number }>(
      `/store/api/messages/inbox?${qs}`,
    );
    setThreads(res.items);
    setTotal(res.total);
  }

  useEffect(() => {
    loadThreads(page).catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, [page, marketplace, sort, orderDir]);

  useEffect(() => {
    if (!customerId) return;
    api<Msg[]>(`/store/api/messages/customer/${customerId}`)
      .then(setMessages)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
    api<{ orders: Order[] }>(`/store/api/admin/customers/${customerId}`)
      .then((c) => {
        setOrders(c.orders || []);
        if (c.orders?.length) setOrderId(c.orders[0].id);
      })
      .catch(() => undefined);
  }, [customerId]);

  const title = useMemo(() => {
    const t = threads.find((x) => x.customer_id === customerId);
    return t?.email || (customerId ? `Customer #${customerId}` : "Select a thread");
  }, [threads, customerId]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function onFilter(e: FormEvent) {
    e.preventDefault();
    setPage(0);
    try {
      await loadThreads(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!orderId || !text.trim()) return;
    setError("");
    try {
      await api(`/store/api/messages/order/${orderId}/send`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      setText("");
      setMessages(await api<Msg[]>(`/store/api/messages/customer/${customerId}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    }
  }

  function selectThread(id: number) {
    setCustomerId(id);
    setSheetOpen(true);
  }

  const composer = customerId ? (
    <form className="stack shrink-0 border-t border-white/10 pt-3" onSubmit={send}>
      <select
        className="field"
        value={orderId ?? ""}
        onChange={(e) => setOrderId(Number(e.target.value))}
      >
        {orders.map((o) => (
          <option key={o.id} value={o.id}>
            #{o.id} {o.marketplace} {o.external_order_id}
          </option>
        ))}
      </select>
      <textarea
        className="field min-h-24 resize-y py-2"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Reply via marketplace chat…"
      />
      <div className="flex justify-end">
        <Button className="button-primary" type="submit" disabled={!orderId || !text.trim()}>
          Send
        </Button>
      </div>
    </form>
  ) : null;

  const messageList = (
    <div className="thread overscroll-contain">
      {messages.map((m) => (
        <div key={m.id} className={`msg ${m.direction === "outbound" ? "out" : "in"}`}>
          <div className="muted">{m.marketplace} · {m.written_at || ""}</div>
          {m.body}
        </div>
      ))}
      {!messages.length && customerId && (
        <p className="muted">No messages — sync happens on open.</p>
      )}
    </div>
  );

  const desktopThread = (
    <div className="flex min-h-0 flex-1 flex-col">
      <h3 className="mb-3 shrink-0 truncate text-base font-semibold">{title}</h3>
      {messageList}
      {composer}
    </div>
  );

  const sheetThread = (
    <div className="flex h-full min-h-0 flex-col p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
      {messageList}
      {composer}
    </div>
  );

  return (
    <div className="space-y-4">
      <h2 className="page-title">Inbox</h2>
      {error && <p className="error">{error}</p>}
      <form className="card filters" onSubmit={onFilter}>
        <input
          className="field sm:min-w-[12rem] sm:flex-1"
          placeholder="Search email / order #"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="field sm:w-auto" value={marketplace} onChange={(e) => { setMarketplace(e.target.value); setPage(0); }}>
          <option value="">all markets</option>
          <option value="ggsel">ggsel</option>
          <option value="digiseller">digiseller</option>
        </select>
        <select className="field sm:w-auto" value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
          <option value="last_at">sort: last activity</option>
          <option value="email">sort: email</option>
          <option value="order_count">sort: order count</option>
        </select>
        <select className="field sm:w-auto" value={orderDir} onChange={(e) => { setOrderDir(e.target.value); setPage(0); }}>
          <option value="desc">desc</option>
          <option value="asc">asc</option>
        </select>
        <Button className="button-primary" type="submit">Search</Button>
      </form>

      <div className="grid gap-4 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)] lg:items-stretch">
        <Card className="flex max-h-[min(28rem,50vh)] flex-col overflow-hidden p-2 lg:max-h-[calc(100vh-12rem)]">
          <div className="min-h-0 flex-1 overflow-y-auto">
            {threads.map((t) => (
              <button
                key={t.customer_id}
                type="button"
                className="mb-1.5 w-full rounded-md border border-transparent p-3 text-left hover:bg-white/5"
                style={{
                  borderColor: t.customer_id === customerId ? "rgba(255,255,255,0.25)" : undefined,
                  background: t.customer_id === customerId ? "rgba(255,255,255,0.08)" : undefined,
                }}
                onClick={() => selectThread(t.customer_id)}
              >
                <div className="truncate text-sm font-medium">{t.email || `Customer #${t.customer_id}`}</div>
                <div className="muted mt-1 line-clamp-2 text-xs">
                  {t.order_count} orders · {t.last_message?.slice(0, 60) || "—"}
                </div>
              </button>
            ))}
            {!threads.length && <p className="muted p-3">No threads yet.</p>}
          </div>
          <div className="pager shrink-0">
            <Button disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <span className="muted">{page + 1} / {pageCount} ({total})</span>
            <Button disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </Card>

        <Card className="hidden h-[calc(100vh-12rem)] min-h-[28rem] flex-col overflow-hidden lg:flex">
          {customerId ? desktopThread : <Empty title="Select a thread" detail="Customer messages will appear here." />}
        </Card>
      </div>

      <Sheet
        open={sheetOpen && !!customerId}
        onClose={() => setSheetOpen(false)}
        title={title}
        wide
        until="lg"
        contentClassName="flex flex-col overflow-hidden p-0"
      >
        {sheetThread}
      </Sheet>
    </div>
  );
}
