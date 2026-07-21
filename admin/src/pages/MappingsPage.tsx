import { FormEvent, useEffect, useMemo, useState } from "react";
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
const BASE = "/store/api/admin/order-params";

const TYPE_COLORS: Record<string, string> = {
  days: "#3d8bfd",
  hwid: "#2dd4a8",
  location: "#f0a05a",
  internal_sq: "#a78bfa",
  external_sq: "#22d3ee",
};

type TreeItem = {
  itemId: number;
  paramGroups: {
    paramId: number;
    userDataGroups: { userDataId: number; params: OrderParam[] }[];
  }[];
};

function buildTree(params: OrderParam[]): TreeItem[] {
  const itemMap = new Map<number, Map<number, Map<number, OrderParam[]>>>();
  for (const p of params) {
    if (!itemMap.has(p.item_id)) itemMap.set(p.item_id, new Map());
    const paramMap = itemMap.get(p.item_id)!;
    if (!paramMap.has(p.param_id)) paramMap.set(p.param_id, new Map());
    const udMap = paramMap.get(p.param_id)!;
    if (!udMap.has(p.user_data_id)) udMap.set(p.user_data_id, []);
    udMap.get(p.user_data_id)!.push(p);
  }
  const tree: TreeItem[] = [];
  for (const [itemId, paramMap] of [...itemMap.entries()].sort((a, b) => a[0] - b[0])) {
    const paramGroups = [];
    for (const [paramId, udMap] of [...paramMap.entries()].sort((a, b) => a[0] - b[0])) {
      const userDataGroups = [];
      for (const [userDataId, ps] of [...udMap.entries()].sort((a, b) => a[0] - b[0])) {
        userDataGroups.push({ userDataId, params: ps });
      }
      paramGroups.push({ paramId, userDataGroups });
    }
    tree.push({ itemId, paramGroups });
  }
  return tree;
}

type Prefill = Partial<Pick<OrderParam, "item_id" | "param_id" | "user_data_id" | "type" | "data">>;

export default function MappingsPage() {
  const [params, setParams] = useState<OrderParam[]>([]);
  const [error, setError] = useState("");
  const [filterItemId, setFilterItemId] = useState("");
  const [openItems, setOpenItems] = useState<Set<number>>(new Set());
  const [openParams, setOpenParams] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<"create" | "edit" | null>(null);
  const [editing, setEditing] = useState<OrderParam | null>(null);
  const [form, setForm] = useState({
    item_id: "",
    param_id: "",
    user_data_id: "",
    type: "days",
    data: "",
  });

  async function load(itemFilter?: string) {
    try {
      const q = itemFilter ? `?item_id=${encodeURIComponent(itemFilter)}` : "";
      setParams(await api<OrderParam[]>(`${BASE}${q}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const tree = useMemo(() => buildTree(params), [params]);

  function openCreate(prefill?: Prefill) {
    setEditing(null);
    setForm({
      item_id: prefill?.item_id != null ? String(prefill.item_id) : "",
      param_id: prefill?.param_id != null ? String(prefill.param_id) : "",
      user_data_id: prefill?.user_data_id != null ? String(prefill.user_data_id) : "",
      type: prefill?.type || "days",
      data: prefill?.data || "",
    });
    setModal("create");
  }

  function openEdit(p: OrderParam) {
    setEditing(p);
    setForm({
      item_id: String(p.item_id),
      param_id: String(p.param_id),
      user_data_id: String(p.user_data_id),
      type: p.type,
      data: p.data,
    });
    setModal("edit");
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    const body = {
      item_id: Number(form.item_id),
      param_id: Number(form.param_id),
      user_data_id: Number(form.user_data_id),
      type: form.type,
      data: form.data,
    };
    try {
      if (editing) {
        await api(`${BASE}/${editing.id}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        await api(BASE, { method: "POST", body: JSON.stringify(body) });
      }
      setModal(null);
      await load(filterItemId || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Delete this parameter?")) return;
    await api(`${BASE}/${id}`, { method: "DELETE" });
    await load(filterItemId || undefined);
  }

  function toggleItem(id: number) {
    setOpenItems((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleParam(itemId: number, paramId: number) {
    const key = `${itemId}:${paramId}`;
    setOpenParams((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Order Parameters</h2>
        <input
          placeholder="Filter by Item ID"
          value={filterItemId}
          onChange={(e) => setFilterItemId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(filterItemId || undefined)}
          style={{ width: 160 }}
        />
        <button onClick={() => load(filterItemId || undefined)}>Filter</button>
        <button className="primary" onClick={() => openCreate()}>Add Parameter</button>
      </div>
      {error && <p className="error">{error}</p>}

      {!tree.length && <div className="card muted">No order parameters found</div>}

      {tree.map((item) => {
        const totalParams = item.paramGroups.reduce(
          (s, pg) => s + pg.userDataGroups.reduce((s2, u) => s2 + u.params.length, 0),
          0,
        );
        const itemOpen = openItems.has(item.itemId);
        return (
          <div key={item.itemId} className="tree-node">
            <div className="tree-head" onClick={() => toggleItem(item.itemId)}>
              <span className="tree-caret">{itemOpen ? "▼" : "▶"}</span>
              <span className="tree-label">item_id</span>
              <span className="tree-value">{item.itemId}</span>
              <span className="muted" style={{ marginLeft: 8 }}>
                {item.paramGroups.length} options / {totalParams} params
              </span>
              <button
                className="tree-add"
                onClick={(e) => {
                  e.stopPropagation();
                  openCreate({ item_id: item.itemId });
                }}
              >
                +
              </button>
            </div>
            {itemOpen && (
              <div className="tree-children">
                {item.paramGroups.map((pg) => {
                  const pKey = `${item.itemId}:${pg.paramId}`;
                  const pOpen = openParams.has(pKey);
                  const pgCount = pg.userDataGroups.reduce((s, u) => s + u.params.length, 0);
                  return (
                    <div key={pg.paramId} className="tree-node nested">
                      <div className="tree-head" onClick={() => toggleParam(item.itemId, pg.paramId)}>
                        <span className="tree-caret">{pOpen ? "▼" : "▶"}</span>
                        <span className="tree-label">param_id</span>
                        <span className="tree-value">{pg.paramId}</span>
                        <span className="muted" style={{ marginLeft: 8 }}>
                          {pg.userDataGroups.length} variants / {pgCount} params
                        </span>
                        <button
                          className="tree-add"
                          onClick={(e) => {
                            e.stopPropagation();
                            openCreate({ item_id: item.itemId, param_id: pg.paramId });
                          }}
                        >
                          +
                        </button>
                      </div>
                      {pOpen && (
                        <div className="tree-children">
                          {pg.userDataGroups.map((udg) => (
                            <div key={udg.userDataId} style={{ marginBottom: 8 }}>
                              <div className="row" style={{ marginBottom: 4 }}>
                                <span className="tree-label">user_data_id</span>
                                <span className="tree-value">{udg.userDataId}</span>
                                <span className="muted">({udg.params.length})</span>
                                <button
                                  className="tree-add"
                                  onClick={() =>
                                    openCreate({
                                      item_id: item.itemId,
                                      param_id: pg.paramId,
                                      user_data_id: udg.userDataId,
                                    })
                                  }
                                >
                                  +
                                </button>
                              </div>
                              {udg.params.map((p) => (
                                <div key={p.id} className="param-row">
                                  <span
                                    className="tag"
                                    style={{ background: `${TYPE_COLORS[p.type] || "#666"}33` }}
                                  >
                                    {p.type}
                                  </span>
                                  <code style={{ flex: 1 }}>{p.data}</code>
                                  <span className="muted">#{p.id}</span>
                                  <button onClick={() => openEdit(p)}>Edit</button>
                                  <button onClick={() => onDelete(p.id)}>Delete</button>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <form className="card modal stack" onClick={(e) => e.stopPropagation()} onSubmit={onSave}>
            <h3 style={{ margin: 0 }}>{editing ? "Edit Order Parameter" : "New Order Parameter"}</h3>
            <label className="muted">Item ID
              <input required value={form.item_id}
                onChange={(e) => setForm({ ...form, item_id: e.target.value })} />
            </label>
            <label className="muted">Param ID
              <input required value={form.param_id}
                onChange={(e) => setForm({ ...form, param_id: e.target.value })} />
            </label>
            <label className="muted">User Data ID
              <input required value={form.user_data_id}
                onChange={(e) => setForm({ ...form, user_data_id: e.target.value })} />
            </label>
            <label className="muted">Type
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="muted">Data
              <input required value={form.data}
                onChange={(e) => setForm({ ...form, data: e.target.value })} />
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
