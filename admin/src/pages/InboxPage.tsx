import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";

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

  return (
    <div>
      <h2>Inbox</h2>
      {error && <p className="error">{error}</p>}
      <form className="card row" onSubmit={onFilter} style={{ marginBottom: "0.75rem" }}>
        <input
          placeholder="Search email / order #"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, minWidth: 160 }}
        />
        <select value={marketplace} onChange={(e) => { setMarketplace(e.target.value); setPage(0); }}>
          <option value="">all markets</option>
          <option value="ggsel">ggsel</option>
          <option value="digiseller">digiseller</option>
        </select>
        <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
          <option value="last_at">sort: last activity</option>
          <option value="email">sort: email</option>
          <option value="order_count">sort: order count</option>
        </select>
        <select value={orderDir} onChange={(e) => { setOrderDir(e.target.value); setPage(0); }}>
          <option value="desc">desc</option>
          <option value="asc">asc</option>
        </select>
        <button className="primary" type="submit">Search</button>
      </form>
      <div className="row" style={{ alignItems: "stretch" }}>
        <div className="card" style={{ width: 300 }}>
          {threads.map((t) => (
            <button
              key={t.customer_id}
              style={{
                width: "100%",
                marginBottom: 6,
                textAlign: "left",
                borderColor: t.customer_id === customerId ? "#3d8bfd" : undefined,
              }}
              onClick={() => setCustomerId(t.customer_id)}
            >
              <div>{t.email || `Customer #${t.customer_id}`}</div>
              <div className="muted">{t.order_count} orders · {t.last_message?.slice(0, 40) || "—"}</div>
            </button>
          ))}
          {!threads.length && <p className="muted">No threads yet.</p>}
          <div className="pager">
            <button disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
            <span className="muted">{page + 1} / {pageCount} ({total})</span>
            <button disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        </div>
        <div className="card" style={{ flex: 1, minWidth: 280 }}>
          <h3 style={{ marginTop: 0 }}>{title}</h3>
          <div className="thread">
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
          {customerId && (
            <form className="stack" onSubmit={send} style={{ marginTop: "0.75rem" }}>
              <select
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
                rows={3}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Reply via marketplace chat…"
              />
              <button className="primary" type="submit" disabled={!orderId || !text.trim()}>
                Send
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
