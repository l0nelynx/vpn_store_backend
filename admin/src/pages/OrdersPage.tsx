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
  const [marketplace, setMarketplace] = useState("");
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
      if (marketplace) q.set("marketplace", marketplace);
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
  }, [page]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPage(0);
    await search(0);
  }

  async function syncSales() {
    setSyncing(true);
    setMsg("");
    setError("");
    try {
      const res = await api<{ ggsel: object; digiseller: object }>(
        "/store/api/admin/sync-orders?top=100",
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
        <button className="primary" onClick={syncSales} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync sales (top 100)"}
        </button>
      </div>
      <p className="muted">
        Remnawave lookups during sync use <code>/api/users/stream</code> (bulk), not per-user GETs.
      </p>
      <form className="card row" onSubmit={onSubmit}>
        <input
          placeholder="Filter by email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ flex: 1, minWidth: 180 }}
        />
        <select value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
          <option value="">all markets</option>
          <option value="ggsel">ggsel</option>
          <option value="digiseller">digiseller</option>
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
