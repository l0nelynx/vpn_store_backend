import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Button, Card, DataList, DetailRow, ListCard } from "../components/ui";

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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="page-title">Mappings</h2>
        <div className="flex flex-wrap gap-2">
          <select
            className="field sm:w-auto"
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
          <Button className="button-primary" onClick={() => openCreate(filterType || "days")}>
            Add mapping
          </Button>
        </div>
      </div>
      <p className="muted">
        Human-readable labels for technical values used in Parameters (days, squads, hwid, …).
      </p>
      {error && <p className="error">{error}</p>}

      {!items.length && <Card className="muted">No mappings yet.</Card>}

      {grouped.map(([type, rows]) => {
        if (filterType && type !== filterType) return null;
        return (
          <Card key={type} className="space-y-3">
            <div className="row">
              <span className="tag" style={{ background: `${TYPE_COLORS[type] || "#666"}33` }}>
                {type}
              </span>
              <span className="muted">{rows.length} values</span>
              <button type="button" className="tree-add" onClick={() => openCreate(type)}>+</button>
            </div>
            <DataList
              table={
                <div className="overflow-x-auto">
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
                            <Button className="h-8" onClick={() => openEdit(m)}>Edit</Button>{" "}
                            <Button className="h-8" onClick={() => onDelete(m.id)}>Delete</Button>
                          </td>
                        </tr>
                      ))}
                      {!rows.length && (
                        <tr><td colSpan={3} className="muted">Empty</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              }
              cards={rows.map((m) => (
                <ListCard
                  key={m.id}
                  title={m.label}
                  subtitle={<code className="text-xs">{m.value}</code>}
                  details={<DetailRow label="Value"><code className="break-all">{m.value}</code></DetailRow>}
                  actions={
                    <>
                      <Button onClick={() => openEdit(m)}>Edit</Button>
                      <Button onClick={() => onDelete(m.id)}>Delete</Button>
                    </>
                  }
                />
              ))}
            />
          </Card>
        );
      })}

      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <form className="modal stack" onClick={(e) => e.stopPropagation()} onSubmit={onSave}>
            <h3 className="m-0 text-base font-semibold">{editing ? "Edit Mapping" : "New Mapping"}</h3>
            <label className="muted">
              Type
              <select className="field mt-1" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="muted">
              Label
              <input
                className="field mt-1"
                required
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="e.g. 1 month"
              />
            </label>
            <label className="muted">
              Value
              <input
                className="field mt-1"
                required
                value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                placeholder="e.g. 30 or squad UUID"
              />
            </label>
            <div className="row">
              <Button type="button" onClick={() => setModal(null)}>Cancel</Button>
              <Button className="button-primary" type="submit">Save</Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
