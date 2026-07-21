import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";

type ValueMapping = {
  id: number;
  type: string;
  label: string;
  value: string;
  created_at: string | null;
};

const TYPES = ["days", "hwid", "location", "internal_sq", "external_sq"];
const BASE = "/store/api/admin/param-mappings";

const TYPE_COLORS: Record<string, string> = {
  days: "#3d8bfd",
  hwid: "#2dd4a8",
  location: "#f0a05a",
  internal_sq: "#a78bfa",
  external_sq: "#22d3ee",
};

export default function MappingsPage() {
  const [items, setItems] = useState<ValueMapping[]>([]);
  const [filterType, setFilterType] = useState("");
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"create" | "edit" | null>(null);
  const [editing, setEditing] = useState<ValueMapping | null>(null);
  const [form, setForm] = useState({ type: "days", label: "", value: "" });

  async function load(typeFilter?: string) {
    try {
      const q = typeFilter ? `?type=${encodeURIComponent(typeFilter)}` : "";
      setItems(await api<ValueMapping[]>(`${BASE}${q}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, ValueMapping[]>();
    for (const t of TYPES) map.set(t, []);
    for (const m of items) {
      if (!map.has(m.type)) map.set(m.type, []);
      map.get(m.type)!.push(m);
    }
    return [...map.entries()].filter(([, rows]) => rows.length > 0 || !filterType);
  }, [items, filterType]);

  function openCreate(type = "days") {
    setEditing(null);
    setForm({ type, label: "", value: "" });
    setModal("create");
  }

  function openEdit(m: ValueMapping) {
    setEditing(m);
    setForm({ type: m.type, label: m.label, value: m.value });
    setModal("edit");
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    const body = {
      type: form.type,
      label: form.label.trim(),
      value: form.value.trim(),
    };
    try {
      if (editing) {
        await api(`${BASE}/${editing.id}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        await api(BASE, { method: "POST", body: JSON.stringify(body) });
      }
      setModal(null);
      await load(filterType || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Delete this mapping?")) return;
    await api(`${BASE}/${id}`, { method: "DELETE" });
    await load(filterType || undefined);
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Mappings</h2>
        <select
          value={filterType}
          onChange={(e) => {
            setFilterType(e.target.value);
            load(e.target.value || undefined);
          }}
        >
          <option value="">all types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <button className="primary" onClick={() => openCreate(filterType || "days")}>
          Add mapping
        </button>
      </div>
      <p className="muted">
        Human-readable labels for technical values used in Parameters (days, squads, hwid, …).
      </p>
      {error && <p className="error">{error}</p>}

      {!items.length && <div className="card muted">No mappings yet.</div>}

      {grouped.map(([type, rows]) => {
        if (filterType && type !== filterType) return null;
        return (
          <div key={type} className="card" style={{ marginBottom: "0.75rem" }}>
            <div className="row" style={{ marginBottom: "0.5rem" }}>
              <span
                className="tag"
                style={{ background: `${TYPE_COLORS[type] || "#666"}33` }}
              >
                {type}
              </span>
              <span className="muted">{rows.length} values</span>
              <button className="tree-add" onClick={() => openCreate(type)}>+</button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Value</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.id}>
                    <td>{m.label}</td>
                    <td><code>{m.value}</code></td>
                    <td>
                      <button onClick={() => openEdit(m)}>Edit</button>{" "}
                      <button onClick={() => onDelete(m.id)}>Delete</button>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={3} className="muted">Empty</td></tr>
                )}
              </tbody>
            </table>
          </div>
        );
      })}

      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <form className="card modal stack" onClick={(e) => e.stopPropagation()} onSubmit={onSave}>
            <h3 style={{ margin: 0 }}>{editing ? "Edit Mapping" : "New Mapping"}</h3>
            <label className="muted">Type
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="muted">Label
              <input required value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="e.g. 1 month" />
            </label>
            <label className="muted">Value
              <input required value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                placeholder="e.g. 30 or squad UUID" />
            </label>
            <div className="row">
              <button type="button" onClick={() => setModal(null)}>Cancel</button>
              <button className="primary" type="submit">Save</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
