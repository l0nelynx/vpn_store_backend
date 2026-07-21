import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type OrderParam = {
  id: number;
  item_id: number;
  param_id: number;
  user_data_id: number;
  type: string;
  data: string;
};

type ValueMapping = {
  id: number;
  type: string;
  label: string;
  value: string;
};

type OptionLabel = {
  id: number;
  marketplace: string;
  item_id: number;
  param_id: number;
  user_data_id: number;
  item_name: string | null;
  param_name: string | null;
  variant_name: string | null;
};

const TYPES = ["days", "hwid", "location", "internal_sq", "external_sq"];
const BASE = "/store/api/admin/order-params";
const MAP_BASE = "/store/api/admin/param-mappings";
const LABELS_BASE = "/store/api/admin/product-option-labels";

const TYPE_COLORS: Record<string, string> = {
  days: "#3d8bfd",
  hwid: "#2dd4a8",
  location: "#f0a05a",
  internal_sq: "#a78bfa",
  external_sq: "#22d3ee",
};

type Prefill = Partial<Pick<OrderParam, "item_id" | "param_id" | "user_data_id" | "type" | "data">>;

type VariantNode = {
  userDataId: number;
  variantName: string | null;
  params: OrderParam[];
};

type ParamNode = {
  paramId: number;
  paramName: string | null;
  variants: VariantNode[];
};

type ItemNode = {
  itemId: number;
  itemName: string | null;
  marketplace: string | null;
  params: ParamNode[];
};

function labelKey(itemId: number, paramId: number, userDataId: number) {
  return `${itemId}:${paramId}:${userDataId}`;
}

function buildMergedTree(params: OrderParam[], labels: OptionLabel[]): ItemNode[] {
  const itemNames = new Map<number, string | null>();
  const paramNames = new Map<string, string | null>();
  const variantNames = new Map<string, string | null>();
  const markets = new Map<number, string>();

  for (const l of labels) {
    itemNames.set(l.item_id, l.item_name);
    markets.set(l.item_id, l.marketplace);
    paramNames.set(`${l.item_id}:${l.param_id}`, l.param_name);
    variantNames.set(labelKey(l.item_id, l.param_id, l.user_data_id), l.variant_name);
  }

  type UdMap = Map<number, OrderParam[]>;
  type PMap = Map<number, UdMap>;
  const itemMap = new Map<number, PMap>();

  function ensure(itemId: number, paramId: number, userDataId: number) {
    if (!itemMap.has(itemId)) itemMap.set(itemId, new Map());
    const pm = itemMap.get(itemId)!;
    if (!pm.has(paramId)) pm.set(paramId, new Map());
    const um = pm.get(paramId)!;
    if (!um.has(userDataId)) um.set(userDataId, []);
    return um.get(userDataId)!;
  }

  for (const p of params) {
    ensure(p.item_id, p.param_id, p.user_data_id).push(p);
  }
  for (const l of labels) {
    ensure(l.item_id, l.param_id, l.user_data_id);
  }

  const tree: ItemNode[] = [];
  for (const [itemId, pm] of [...itemMap.entries()].sort((a, b) => a[0] - b[0])) {
    const paramNodes: ParamNode[] = [];
    for (const [paramId, um] of [...pm.entries()].sort((a, b) => a[0] - b[0])) {
      const variants: VariantNode[] = [];
      for (const [userDataId, ps] of [...um.entries()].sort((a, b) => a[0] - b[0])) {
        variants.push({
          userDataId,
          variantName: variantNames.get(labelKey(itemId, paramId, userDataId)) ?? null,
          params: ps,
        });
      }
      paramNodes.push({
        paramId,
        paramName: paramNames.get(`${itemId}:${paramId}`) ?? null,
        variants,
      });
    }
    tree.push({
      itemId,
      itemName: itemNames.get(itemId) ?? null,
      marketplace: markets.get(itemId) ?? null,
      params: paramNodes,
    });
  }
  return tree;
}

export default function ParametersPage() {
  const [params, setParams] = useState<OrderParam[]>([]);
  const [labels, setLabels] = useState<OptionLabel[]>([]);
  const [mappings, setMappings] = useState<ValueMapping[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);
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
  const [dataMode, setDataMode] = useState<"pick" | "custom">("pick");

  async function load(itemFilter?: string) {
    try {
      const q = itemFilter ? `?item_id=${encodeURIComponent(itemFilter)}` : "";
      const labelQ = itemFilter ? `?item_id=${encodeURIComponent(itemFilter)}` : "";
      const [p, m, l] = await Promise.all([
        api<OrderParam[]>(`${BASE}${q}`),
        api<ValueMapping[]>(MAP_BASE),
        api<OptionLabel[]>(`${LABELS_BASE}${labelQ}`),
      ]);
      setParams(p);
      setMappings(m);
      setLabels(l);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const tree = useMemo(() => buildMergedTree(params, labels), [params, labels]);
  const optionsForType = useMemo(
    () => mappings.filter((m) => m.type === form.type),
    [mappings, form.type],
  );

  function syncDataMode(type: string, data: string) {
    const match = mappings.some((m) => m.type === type && m.value === data);
    setDataMode(match || !data ? "pick" : "custom");
  }

  function openCreate(prefill?: Prefill) {
    setEditing(null);
    const type = prefill?.type || "days";
    const data = prefill?.data || "";
    setForm({
      item_id: prefill?.item_id != null ? String(prefill.item_id) : "",
      param_id: prefill?.param_id != null ? String(prefill.param_id) : "",
      user_data_id: prefill?.user_data_id != null ? String(prefill.user_data_id) : "",
      type,
      data,
    });
    syncDataMode(type, data);
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
    syncDataMode(p.type, p.data);
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

  async function syncOptions() {
    setSyncing(true);
    setMsg("");
    setError("");
    try {
      const res = await api<object>("/store/api/admin/sync-product-options", { method: "POST" });
      setMsg(JSON.stringify(res));
      await load(filterItemId || undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
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

  function mappingLabel(type: string, value: string) {
    const m = mappings.find((x) => x.type === type && x.value === value);
    return m ? m.label : null;
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Parameters</h2>
        <input
          placeholder="Filter by Item ID"
          value={filterItemId}
          onChange={(e) => setFilterItemId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(filterItemId || undefined)}
          style={{ width: 160 }}
        />
        <button onClick={() => load(filterItemId || undefined)}>Filter</button>
        <button onClick={syncOptions} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync options from products"}
        </button>
        <button className="primary" onClick={() => openCreate()}>Add Parameter</button>
      </div>
      <p className="muted">
        Tree merges marketplace option names (API v1) with your mappings. Assign values from{" "}
        <Link to="/value-mappings">Mappings</Link>; manual Add still works.
      </p>
      {msg && <p className="muted" style={{ wordBreak: "break-all" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      {!tree.length && (
        <div className="card muted">
          No parameters or synced options yet — sync catalog, then Sync options.
        </div>
      )}

      {tree.map((item) => {
        const mappedCount = item.params.reduce(
          (s, pg) => s + pg.variants.reduce((s2, v) => s2 + v.params.length, 0),
          0,
        );
        const variantCount = item.params.reduce((s, pg) => s + pg.variants.length, 0);
        const itemOpen = openItems.has(item.itemId);
        const itemTitle = item.itemName
          ? `${item.itemName} (${item.itemId})`
          : `item_id ${item.itemId}`;
        return (
          <div key={item.itemId} className="tree-node">
            <div className="tree-head" onClick={() => toggleItem(item.itemId)}>
              <span className="tree-caret">{itemOpen ? "▼" : "▶"}</span>
              <span className="tree-label">item</span>
              <span className="tree-value">{itemTitle}</span>
              {item.marketplace && <span className="tag">{item.marketplace}</span>}
              <span className="muted" style={{ marginLeft: 8 }}>
                {item.params.length} options / {variantCount} variants / {mappedCount} mapped
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
                {item.params.map((pg) => {
                  const pKey = `${item.itemId}:${pg.paramId}`;
                  const pOpen = openParams.has(pKey);
                  const paramTitle = pg.paramName
                    ? `${pg.paramName} (${pg.paramId})`
                    : `param_id ${pg.paramId}`;
                  return (
                    <div key={pg.paramId} className="tree-node nested">
                      <div className="tree-head" onClick={() => toggleParam(item.itemId, pg.paramId)}>
                        <span className="tree-caret">{pOpen ? "▼" : "▶"}</span>
                        <span className="tree-label">option</span>
                        <span className="tree-value">{paramTitle}</span>
                        <span className="muted" style={{ marginLeft: 8 }}>
                          {pg.variants.length} variants
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
                          {pg.variants.map((udg) => {
                            const vTitle = udg.variantName
                              ? `${udg.variantName} (${udg.userDataId})`
                              : `user_data_id ${udg.userDataId}`;
                            return (
                              <div key={udg.userDataId} style={{ marginBottom: 8 }}>
                                <div className="row" style={{ marginBottom: 4 }}>
                                  <span className="tree-label">variant</span>
                                  <span className="tree-value">{vTitle}</span>
                                  <span className="muted">({udg.params.length} mapped)</span>
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
                                    {udg.params.length ? "+" : "Assign"}
                                  </button>
                                </div>
                                {udg.params.map((p) => {
                                  const lbl = mappingLabel(p.type, p.data);
                                  return (
                                    <div key={p.id} className="param-row">
                                      <span
                                        className="tag"
                                        style={{ background: `${TYPE_COLORS[p.type] || "#666"}33` }}
                                      >
                                        {p.type}
                                      </span>
                                      <code style={{ flex: 1 }}>
                                        {lbl ? `${lbl} → ${p.data}` : p.data}
                                      </code>
                                      <span className="muted">#{p.id}</span>
                                      <button onClick={() => openEdit(p)}>Edit</button>
                                      <button onClick={() => onDelete(p.id)}>Delete</button>
                                    </div>
                                  );
                                })}
                                {!udg.params.length && (
                                  <div className="param-row muted">
                                    Unmapped — Assign a Mapping value for this variant.
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
              </div>
            )}
          </div>
        );
      })}

      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <form className="card modal stack" onClick={(e) => e.stopPropagation()} onSubmit={onSave}>
            <h3 style={{ margin: 0 }}>{editing ? "Edit Parameter" : "Assign / New Parameter"}</h3>
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
              <select
                value={form.type}
                onChange={(e) => {
                  const type = e.target.value;
                  setForm({ ...form, type, data: "" });
                  setDataMode("pick");
                }}
              >
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="muted">Value source
              <select
                value={dataMode}
                onChange={(e) => setDataMode(e.target.value as "pick" | "custom")}
              >
                <option value="pick">From Mappings</option>
                <option value="custom">Custom (manual)</option>
              </select>
            </label>
            {dataMode === "pick" ? (
              <label className="muted">Mapping
                <select
                  required
                  value={form.data}
                  onChange={(e) => setForm({ ...form, data: e.target.value })}
                >
                  <option value="">Select…</option>
                  {optionsForType.map((m) => (
                    <option key={m.id} value={m.value}>
                      {m.label} ({m.value})
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="muted">Data
                <input required value={form.data}
                  onChange={(e) => setForm({ ...form, data: e.target.value })} />
              </label>
            )}
            {dataMode === "pick" && !optionsForType.length && (
              <p className="muted">No mappings for this type — add them under Mappings, or use Custom.</p>
            )}
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
