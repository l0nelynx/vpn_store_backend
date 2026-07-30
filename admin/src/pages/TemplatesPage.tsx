import { useEffect, useState } from "react";
import { Plus, Save } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { Badge, Button, Card, Empty, Input, cn } from "../components/ui";

type Template = { id: number; key: string; provider: string; name: string; format: string; body: string; enabled: boolean };

export default function TemplatesPage() {
  const [items, setItems] = useState<Template[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const load = () => api<Template[]>("/store/api/v1/templates").then((rows) => {
    setItems(rows);
    if (!selectedId && rows[0]) setSelectedId(rows[0].id);
  });
  useEffect(() => { load(); }, []);
  const current = items.find((row) => row.id === selectedId) || null;

  function patch(values: Partial<Template>) {
    setItems((rows) => rows.map((row) => row.id === selectedId ? { ...row, ...values } : row));
  }
  async function create() {
    const name = prompt("Template name");
    if (!name) return;
    const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "message";
    const created = await api<Template>("/store/api/v1/templates", {
      method: "POST",
      body: JSON.stringify({ key: `${base}_${Date.now()}`, provider: "ggsel", name, format: "plain", body: "", enabled: true }),
    });
    toast.success("Template created");
    await load();
    setSelectedId(created.id);
  }
  async function save() {
    if (!current) return;
    await api(`/store/api/v1/templates/${current.id}`, { method: "PUT", body: JSON.stringify(current) });
    toast.success("Template saved");
    await load();
  }

  return <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
    <Card className="p-2">
      <div className="flex items-center justify-between p-2">
        <div><h2 className="text-sm font-semibold">Templates</h2><p className="text-xs text-muted-foreground">Separate by provider</p></div>
        <Button className="h-8 w-8 px-0" onClick={create}><Plus className="h-4 w-4" /></Button>
      </div>
      {items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={cn("mb-1 w-full rounded-md p-3 text-left hover:bg-white/5", selectedId === item.id && "bg-white/8")}>
        <div className="flex justify-between gap-2"><span className="text-sm font-medium">{item.name}</span><Badge>{item.provider}</Badge></div>
        <code className="text-[11px] text-muted-foreground">{item.key}</code>
      </button>)}
    </Card>
    <Card>{!current ? <Empty title="No templates" detail="Create a message template for a delivery step." /> : <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div><p className="text-xs uppercase tracking-wider text-muted-foreground">Message editor</p><h2 className="mt-1 text-lg font-semibold">{current.name}</h2></div>
        <Button className="button-primary" onClick={save}><Save className="h-4 w-4" />Save changes</Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label><span className="label">Provider</span><select className="field w-full" value={current.provider} onChange={(event) => patch({ provider: event.target.value })}><option>ggsel</option><option>digiseller</option></select></label>
        <label><span className="label">Format</span><select className="field w-full" value={current.format} onChange={(event) => patch({ format: event.target.value })}><option>plain</option><option>html</option></select></label>
        <label><span className="label">Stable key</span><Input className="w-full font-mono" value={current.key} onChange={(event) => patch({ key: event.target.value })} /></label>
      </div>
      <label><span className="label">Name</span><Input className="w-full" value={current.name} onChange={(event) => patch({ name: event.target.value })} /></label>
      <label><span className="label">Message</span><textarea className="field min-h-80 w-full resize-y p-4 font-mono text-sm" value={current.body} onChange={(event) => patch({ body: event.target.value })} /></label>
      <div className="rounded-md border bg-white/2 p-3"><p className="text-xs font-medium">Available example</p><code className="mt-1 block text-xs text-muted-foreground">{"{{ steps.provision.outputs.subscription_url }}"}</code></div>
    </div>}</Card>
  </div>;
}
