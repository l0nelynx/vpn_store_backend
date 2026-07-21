import { useEffect, useState } from "react";
import { api } from "../api";

type Product = {
  id: number;
  marketplace: string;
  external_item_id: number;
  name: string | null;
  price: number | null;
  currency: string | null;
  is_hidden: boolean;
};

export default function ProductsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setItems(await api<Product[]>("/store/api/admin/products"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function sync() {
    setSyncing(true);
    setMsg("");
    try {
      const res = await api<{ ggsel: number; digiseller: number }>(
        "/store/api/admin/sync-catalog",
        { method: "POST" },
      );
      setMsg(`Synced GGsel=${res.ggsel}, Digiseller=${res.digiseller}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Products</h2>
        <button className="primary" onClick={sync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync catalogs"}
        </button>
      </div>
      {msg && <p className="muted">{msg}</p>}
      {error && <p className="error">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Marketplace</th>
              <th>Item ID</th>
              <th>Name</th>
              <th>Price</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td><span className="tag">{p.marketplace}</span></td>
                <td>{p.external_item_id}</td>
                <td>{p.name || "—"}</td>
                <td>{p.price != null ? `${p.price} ${p.currency || ""}` : "—"}</td>
              </tr>
            ))}
            {!items.length && (
              <tr><td colSpan={4} className="muted">No products — run sync.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
