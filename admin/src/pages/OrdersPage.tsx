import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type Order = {
  id: number;
  marketplace: string;
  external_order_id: string;
  email: string | null;
  customer_id: number | null;
  remnawave_username: string | null;
  remnawave_uuid: string | null;
  days_ordered: number | null;
  status: string;
  delivery_status: number;
  created_at: string | null;
};

const PAGE_SIZE = 50;

export default function OrdersPage() {
  const [email, setEmail] = useState("");
  const [orderQ, setOrderQ] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [sort, setSort] = useState("created_at");
  const [orderDir, setOrderDir] = useState("desc");
  const [top, setTop] = useState(100);
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);

  async function search(p = page) {
    setError("");
    try {
      const q = new URLSearchParams();
      if (email) q.set("email", email);
      if (orderQ.trim()) q.set("q", orderQ.trim());
      if (marketplace) q.set("marketplace", marketplace);
      q.set("sort", sort);
      q.set("order", orderDir);
      q.set("limit", String(PAGE_SIZE));
      q.set("offset", String(p * PAGE_SIZE));
      const res = await api<{ items: Order[]; total: number }>(
        `/store/api/admin/orders?${q}`,
      );
      setOrders(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  useEffect(() => {
    search(page);
  }, [page, sort, orderDir]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPage(0);
    await search(0);
  }

  async function syncSales() {
    const n = Math.min(200, Math.max(1, Number(top) || 100));
    setTop(n);
    setSyncing(true);
    setMsg("");
    setError("");
    try {
      const res = await api<{ ggsel: object; digiseller: object }>(
        `/store/api/admin/sync-orders?top=${n}`,
        { method: "POST" },
      );
      setMsg(JSON.stringify(res));
      await search(page);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Orders</h2>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          top
          <input
            type="number"
            min={1}
            max={200}
            value={top}
            onChange={(e) => setTop(Number(e.target.value))}
            style={{ width: 72 }}
          />
        </label>
        <button className="primary" onClick={syncSales} disabled={syncing}>
          {syncing ? "Syncing…" : `Sync sales (top ${top})`}
        </button>
      </div>
      <p className="muted">
        Already-delivered orders are skipped via a batch DB lookup before marketplace detail /
        Remnawave stream. Lookups use <code>/api/users/stream</code>.
      </p>
      <form className="card row" onSubmit={onSubmit}>
        <input
          placeholder="Filter by email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ flex: 1, minWidth: 140 }}
        />
        <input
          placeholder="Order / invoice #"
          value={orderQ}
          onChange={(e) => setOrderQ(e.target.value)}
          style={{ flex: 1, minWidth: 140 }}
        />
        <select value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
          <option value="">all markets</option>
          <option value="ggsel">ggsel</option>
          <option value="digiseller">digiseller</option>
        </select>
        <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
          <option value="created_at">sort: created</option>
          <option value="external_order_id">sort: order id</option>
          <option value="marketplace">sort: market</option>
          <option value="delivery_status">sort: delivery</option>
        </select>
        <select value={orderDir} onChange={(e) => { setOrderDir(e.target.value); setPage(0); }}>
          <option value="desc">desc</option>
          <option value="asc">asc</option>
        </select>
        <button className="primary" type="submit">Search</button>
      </form>
      {msg && <p className="muted" style={{ wordBreak: "break-all" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Market</th><th>External</th><th>Email</th>
              <th>RW user</th><th>Days</th><th>Status</th><th />
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td><span className="tag">{o.marketplace}</span></td>
                <td>{o.external_order_id}</td>
                <td>{o.email || "—"}</td>
                <td style={{ wordBreak: "break-all" }}>{o.remnawave_username}</td>
                <td>{o.days_ordered}</td>
                <td>{o.status} / d{o.delivery_status}</td>
                <td>
                  {o.customer_id != null && (
                    <Link to={`/customers/${o.customer_id}`}>Customer</Link>
                  )}
                </td>
              </tr>
            ))}
            {!orders.length && (
              <tr><td colSpan={8} className="muted">No orders — Search or Sync sales.</td></tr>
            )}
          </tbody>
        </table>
        <div className="pager">
          <button disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
          <span className="muted">{page + 1} / {pageCount} ({total})</span>
          <button disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>Next</button>
        </div>
      </div>
    </div>
  );
}
