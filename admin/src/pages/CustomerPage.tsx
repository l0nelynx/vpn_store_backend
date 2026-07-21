import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";

type Customer360 = {
  id: number;
  email: string | null;
  order_count: number;
  orders: Array<{
    id: number;
    marketplace: string;
    external_order_id: string;
    remnawave_username: string | null;
    remnawave_uuid: string | null;
    subscription_url: string | null;
    status: string;
    created_at: string | null;
  }>;
};

export default function CustomerPage() {
  const { id } = useParams();
  const [data, setData] = useState<Customer360 | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Customer360>(`/store/api/admin/customers/${id}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <p className="muted"><Link to="/orders">← Orders</Link></p>
      <h2>Customer #{data.id}</h2>
      <div className="card">
        <p><strong>Email:</strong> {data.email || "—"}</p>
        <p><strong>Orders:</strong> {data.order_count}</p>
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Order</th><th>Market</th><th>External</th><th>RW</th><th>Created</th>
            </tr>
          </thead>
          <tbody>
            {data.orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>{o.marketplace}</td>
                <td>{o.external_order_id}</td>
                <td style={{ wordBreak: "break-all" }}>{o.remnawave_username}</td>
                <td>{o.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <Link to={`/inbox?customer=${data.id}`}>Open inbox thread →</Link>
      </p>
    </div>
  );
}
