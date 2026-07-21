import { FormEvent, useState } from "react";
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

export default function OrdersPage() {
  const [email, setEmail] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");

  async function search(e?: FormEvent) {
    e?.preventDefault();
    setError("");
    try {
      const q = email ? `?email=${encodeURIComponent(email)}` : "";
      setOrders(await api<Order[]>(`/store/api/admin/orders${q}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div>
      <h2>Orders</h2>
      <form className="card row" onSubmit={search}>
        <input
          placeholder="Filter by email (optional)"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ flex: 1, minWidth: 220 }}
        />
        <button className="primary" type="submit">Search</button>
      </form>
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
              <tr><td colSpan={8} className="muted">No orders loaded — press Search.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
