import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Button, Card, DataList, DetailRow, Empty, ListCard } from "../components/ui";

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
      const res = await api<{ items: Order[]; total: number }>(`/store/api/admin/orders?${q}`);
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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="page-title">Orders</h2>
        <div className="flex flex-wrap items-center gap-2">
          <label className="muted flex items-center gap-2 text-sm">
            top
            <input
              className="field w-20"
              type="number"
              min={1}
              max={200}
              value={top}
              onChange={(e) => setTop(Number(e.target.value))}
            />
          </label>
          <Button className="button-primary" onClick={syncSales} disabled={syncing}>
            {syncing ? "Syncing…" : `Sync sales (top ${top})`}
          </Button>
        </div>
      </div>
      <p className="muted">
        Already-delivered orders are skipped via a batch DB lookup before marketplace detail /
        Remnawave stream. Lookups use <code>/api/users/stream</code>.
      </p>
      <form className="card filters" onSubmit={onSubmit}>
        <input
          className="field sm:min-w-[10rem] sm:flex-1"
          placeholder="Filter by email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="field sm:min-w-[10rem] sm:flex-1"
          placeholder="Order / invoice #"
          value={orderQ}
          onChange={(e) => setOrderQ(e.target.value)}
        />
        <select className="field sm:w-auto" value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
          <option value="">all markets</option>
          <option value="ggsel">ggsel</option>
          <option value="digiseller">digiseller</option>
        </select>
        <select className="field sm:w-auto" value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
          <option value="created_at">sort: created</option>
          <option value="external_order_id">sort: order id</option>
          <option value="marketplace">sort: market</option>
          <option value="delivery_status">sort: delivery</option>
        </select>
        <select className="field sm:w-auto" value={orderDir} onChange={(e) => { setOrderDir(e.target.value); setPage(0); }}>
          <option value="desc">desc</option>
          <option value="asc">asc</option>
        </select>
        <Button className="button-primary" type="submit">Search</Button>
      </form>
      {msg && <p className="muted break-all">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <Card className="p-0 md:p-0">
        <DataList
          className="p-0"
          table={
            <div className="overflow-x-auto">
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
                      <td className="break-all">{o.remnawave_username}</td>
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
            </div>
          }
          cards={
            <div className="space-y-2 p-3">
              {orders.map((o) => (
                <ListCard
                  key={o.id}
                  title={`#${o.id} · ${o.external_order_id}`}
                  subtitle={o.email || "No email"}
                  badges={
                    <>
                      <Badge>{o.marketplace}</Badge>
                      <Badge tone={o.delivery_status >= 1 ? "success" : "warning"}>
                        {o.status} / d{o.delivery_status}
                      </Badge>
                    </>
                  }
                  details={
                    <>
                      <DetailRow label="RW user">{o.remnawave_username || "—"}</DetailRow>
                      <DetailRow label="Days">{o.days_ordered ?? "—"}</DetailRow>
                      <DetailRow label="Created">{o.created_at || "—"}</DetailRow>
                    </>
                  }
                  actions={
                    o.customer_id != null ? (
                      <Link className="button button-primary" to={`/customers/${o.customer_id}`}>Customer</Link>
                    ) : undefined
                  }
                />
              ))}
              {!orders.length && <Empty title="No orders" detail="Search or Sync sales." />}
            </div>
          }
        />
        <div className="pager px-3 pb-3">
          <Button disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>Prev</Button>
          <span className="muted">{page + 1} / {pageCount} ({total})</span>
          <Button disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      </Card>
    </div>
  );
}
