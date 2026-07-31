import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, DataList, DetailRow, Empty, ListCard } from "../components/ui";

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
    <div className="space-y-4">
      <p className="muted"><Link to="/orders">← Orders</Link></p>
      <h2 className="page-title">Customer #{data.id}</h2>
      <Card>
        <p><strong>Email:</strong> {data.email || "—"}</p>
        <p className="mt-1"><strong>Orders:</strong> {data.order_count}</p>
      </Card>
      <DataList
        table={
          <Card className="overflow-x-auto p-0">
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
                    <td className="break-all">{o.remnawave_username}</td>
                    <td>{o.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        }
        cards={
          data.orders.length ? data.orders.map((o) => (
            <ListCard
              key={o.id}
              title={`Order #${o.id}`}
              subtitle={o.external_order_id}
              badges={<Badge>{o.marketplace}</Badge>}
              details={
                <>
                  <DetailRow label="RW">{o.remnawave_username || "—"}</DetailRow>
                  <DetailRow label="Status">{o.status}</DetailRow>
                  <DetailRow label="Created">{o.created_at || "—"}</DetailRow>
                </>
              }
            />
          )) : <Empty title="No orders" detail="This customer has no orders yet." />
        }
      />
      <p>
        <Link to={`/inbox?customer=${data.id}`}>Open inbox thread →</Link>
      </p>
    </div>
  );
}
