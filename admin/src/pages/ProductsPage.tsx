import { useEffect, useState } from "react";
import { Link2, PackagePlus, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { Badge, Button, Card, Empty, Input } from "../components/ui";

type Binding = { id: number; provider: string; external_item_id: number; status: string; published_pipeline_version_id: number | null };
type Product = { id: number; key: string; name: string; description: string | null; status: string; bindings: Binding[] };

export default function ProductsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api<Product[]>("/store/api/v1/products").then(setItems);
  useEffect(() => { load(); }, []);

  async function create() {
    if (!name || !key) return;
    await api("/store/api/v1/products", { method: "POST", body: JSON.stringify({ name, key, status: "draft" }) });
    setName(""); setKey(""); toast.success("Product created"); await load();
  }
  async function addBinding(productId: number) {
    const provider = prompt("Provider: ggsel or digiseller", "ggsel");
    if (provider !== "ggsel" && provider !== "digiseller") return;
    const rawItemId = prompt("Marketplace item ID");
    const externalItemId = Number(rawItemId);
    if (!Number.isSafeInteger(externalItemId) || externalItemId <= 0) return;
    await api(`/store/api/v1/products/${productId}/bindings`, {
      method: "POST",
      body: JSON.stringify({ provider, external_item_id: externalItemId, trigger_policy: "automatic", option_mappings: {}, status: "active" }),
    });
    toast.success("Marketplace binding added"); await load();
  }
  async function sync() {
    setBusy(true);
    try { await api("/store/api/v1/sync/catalog", { method: "POST" }); toast.success("Catalogs synchronized"); await load(); }
    finally { setBusy(false); }
  }

  return <div className="space-y-5">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h2 className="page-title">Unified catalog</h2><p className="muted mt-1">One product can own several marketplace listings.</p></div>
      <Button onClick={sync}><RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />Sync marketplace catalogs</Button>
    </div>
    <Card className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
      <label><span className="label">Product name</span><Input className="w-full" value={name} onChange={(event) => setName(event.target.value)} placeholder="VPN · 90 days" /></label>
      <label><span className="label">Stable key</span><Input className="w-full font-mono" value={key} onChange={(event) => setKey(event.target.value)} placeholder="vpn_90_days" /></label>
      <Button className="button-primary self-end" onClick={create}><PackagePlus className="h-4 w-4" />Create product</Button>
    </Card>
    {!items.length ? <Empty title="No products" detail="Synchronize the marketplaces or create the first local product." /> : <div className="grid gap-3 lg:grid-cols-2">
      {items.map((product) => <Card key={product.id} className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div><h3 className="font-medium">{product.name}</h3><code className="text-xs text-muted-foreground">{product.key}</code></div>
          <Badge tone={product.status === "active" ? "success" : "warning"}>{product.status}</Badge>
        </div>
        <div className="space-y-2">{product.bindings.map((binding) => <div key={binding.id} className="flex items-center justify-between rounded-md border bg-white/2 p-3 text-sm">
          <span className="flex items-center gap-2"><Link2 className="h-4 w-4 text-muted-foreground" /><b>{binding.provider}</b> #{binding.external_item_id} <code className="text-[10px] text-muted-foreground">binding:{binding.id}</code></span>
          <div className="flex gap-2"><Badge tone={binding.status === "active" ? "success" : "warning"}>{binding.status}</Badge>{binding.published_pipeline_version_id && <Badge>v{binding.published_pipeline_version_id}</Badge>}</div>
        </div>)}{!product.bindings.length && <p className="muted">No marketplace bindings.</p>}</div>
        <Button className="w-full border-dashed" onClick={() => addBinding(product.id)}><Plus className="h-4 w-4" />Add marketplace binding</Button>
      </Card>)}
    </div>}
  </div>;
}
