import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";

type OrderParam = {
  id: number;
  item_id: number;
  param_id: number;
  user_data_id: number;
  type: string;
  data: string;
};

const TYPES = ["days", "hwid", "location", "internal_sq", "external_sq"];

export default function MappingsPage() {
  const [params, setParams] = useState<OrderParam[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    item_id: "",
    param_id: "",
    user_data_id: "",
    type: "days",
    data: "",
  });

  async function load() {
    try {
      setParams(await api<OrderParam[]>("/store/api/order-params/"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/store/api/order-params/", {
        method: "POST",
        body: JSON.stringify({
          item_id: Number(form.item_id),
          param_id: Number(form.param_id),
          user_data_id: Number(form.user_data_id),
          type: form.type,
          data: form.data,
        }),
      });
      setForm({ ...form, data: "" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function onDelete(id: number) {
    await api(`/store/api/order-params/${id}`, { method: "DELETE" });
    await load();
  }

  return (
    <div>
      <h2>Option → Remnawave mappings</h2>
      <p className="muted">
        Same contract as dashboard Store page (`item_id` / `param_id` / `user_data_id`).
      </p>
      {error && <p className="error">{error}</p>}
      <form className="card row" onSubmit={onCreate}>
        <input placeholder="item_id" value={form.item_id}
          onChange={(e) => setForm({ ...form, item_id: e.target.value })} required />
        <input placeholder="param_id" value={form.param_id}
          onChange={(e) => setForm({ ...form, param_id: e.target.value })} required />
        <input placeholder="user_data_id" value={form.user_data_id}
          onChange={(e) => setForm({ ...form, user_data_id: e.target.value })} required />
        <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input placeholder="data" value={form.data}
          onChange={(e) => setForm({ ...form, data: e.target.value })} required />
        <button className="primary" type="submit">Add</button>
      </form>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>item</th><th>param</th><th>user_data</th><th>type</th><th>data</th><th />
            </tr>
          </thead>
          <tbody>
            {params.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td>{p.item_id}</td>
                <td>{p.param_id}</td>
                <td>{p.user_data_id}</td>
                <td><span className="tag">{p.type}</span></td>
                <td style={{ wordBreak: "break-all" }}>{p.data}</td>
                <td>
                  <button onClick={() => onDelete(p.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
