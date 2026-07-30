import { useEffect, useMemo, useRef, useState } from "react";
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Check, CircleDot, Clock3, Copy, GripVertical, Plus, RefreshCw, Rocket, Save, Send, TestTube2, Trash2, Webhook, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { Badge, Button, Card, Empty, Input, cn } from "../components/ui";

type Step = { id?: number; key: string; phase: "trigger" | "action" | "delivery"; type: string; condition?: object | null; required: boolean; retry_policy: object; timeout_seconds: number; config: Record<string, unknown>; idempotency_key_template?: string | null; run_before_response: boolean };
type Version = { id: number; version: number; status: string; steps: Step[] };
type Pipeline = { id: number; key: string; name: string; providers: string[]; current_draft_version_id: number | null; published_version_id: number | null; versions: Version[] };

const TYPES = {
  action: ["remnawave.provision_subscription", "remnawave.update_user", "http.request"],
  delivery: ["webhook.response", "marketplace.message"],
};

function icon(step: Step) {
  if (step.type === "webhook.response") return <Webhook className="h-4 w-4" />;
  if (step.type === "marketplace.message") return <Send className="h-4 w-4" />;
  if (step.phase === "trigger") return <CircleDot className="h-4 w-4" />;
  return <Zap className="h-4 w-4" />;
}

function SortableStep({ step, active, onSelect }: { step: Step; active: boolean; onSelect(): void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: step.key });
  return <button ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} onClick={onSelect}
    className={cn("rail-enter group flex w-full items-center gap-3 rounded-lg border bg-card p-3 text-left transition-colors", active && "border-white/40 bg-white/7", isDragging && "z-20 opacity-60 shadow-xl")}>
    <span {...attributes} {...listeners} className="cursor-grab text-muted-foreground"><GripVertical className="h-4 w-4" /></span>
    <span className="grid h-8 w-8 place-items-center rounded-md border bg-white/3">{icon(step)}</span>
    <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{step.key}</span><span className="block truncate font-mono text-[11px] text-muted-foreground">{step.type}</span></span>
    <span className="flex gap-1">{step.required && <Badge>required</Badge>}{step.run_before_response && <Badge tone="sync">sync</Badge>}</span>
  </button>;
}

function ConfigEditor({ step, disabled, chips, onChange }: { step: Step; disabled: boolean; chips: string[]; onChange(config: Record<string, unknown>): void }) {
  const [text, setText] = useState(() => JSON.stringify(step.config, null, 2));
  const [error, setError] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { setText(JSON.stringify(step.config, null, 2)); setError(""); }, [step.id, step.key]);
  function update(next: string) { setText(next); try { onChange(JSON.parse(next)); setError(""); } catch { setError("JSON is not valid"); } }
  function insert(path: string) {
    const token = `{{ ${path} }}`; const node = ref.current; const start = node?.selectionStart ?? text.length; const end = node?.selectionEnd ?? start;
    update(text.slice(0, start) + token + text.slice(end));
    requestAnimationFrame(() => { node?.focus(); node?.setSelectionRange(start + token.length, start + token.length); });
  }
  return <label><span className="label">Configuration · JSON</span>
    <textarea ref={ref} className="field h-56 w-full resize-y p-3 font-mono text-xs" disabled={disabled} value={text} onChange={(e) => update(e.target.value)} />
    {error && <span className="error">{error}</span>}
    {!disabled && <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Available pipeline variables">{chips.map((path) => <button type="button" key={path} title={`Insert {{ ${path} }}`} onClick={() => insert(path)} className="rounded border bg-white/3 px-2 py-1 font-mono text-[10px] text-muted-foreground transition-colors hover:border-white/30 hover:text-foreground">{path}</button>)}</div>}
  </label>;
}

export default function PipelinesPage() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]); const [pipelineId, setPipelineId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null); const [steps, setSteps] = useState<Step[]>([]); const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [provider, setProvider] = useState("digiseller");
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const load = async () => { const rows = await api<Pipeline[]>("/store/api/v1/pipelines"); setPipelines(rows); if (!pipelineId && rows[0]) setPipelineId(rows[0].id); };
  useEffect(() => { load(); }, []);
  const pipeline = pipelines.find((row) => row.id === pipelineId) || null;
  useEffect(() => { if (!pipeline) return; const version = pipeline.versions.find((v) => v.id === pipeline.current_draft_version_id) || pipeline.versions[0]; setVersionId(version?.id || null); setSteps(version?.steps || []); setSelectedKey(version?.steps[0]?.key || null); }, [pipelineId, pipelines]);
  const version = pipeline?.versions.find((row) => row.id === versionId); const isDraft = version?.status === "draft";
  const selected = steps.find((step) => step.key === selectedKey) || null;
  const variableChips = useMemo(() => {
    const base = ["order.provider_order_id", "order.content_id", "buyer.email", "product.name", "product.parameters.days", "system.run_id", "system.correlation_id"];
    const selectedIndex = steps.findIndex((step) => step.key === selectedKey);
    for (const producer of steps.slice(0, Math.max(0, selectedIndex))) {
      const configured = Object.keys((producer.config.outputs as Record<string, unknown> | undefined) || {});
      const known = producer.type === "remnawave.provision_subscription" ? ["uuid", "username", "subscription_url", "days"] : configured;
      for (const output of known) base.push(`steps.${producer.key}.outputs.${output}`);
    }
    return [...new Set(base)];
  }, [steps, selectedKey]);
  const syncBudget = steps.filter((step) => step.run_before_response).reduce((sum, step) => sum + step.timeout_seconds, 0);
  const sections = ["trigger", "action", "delivery"] as const;
  function dragEnd(event: DragEndEvent) { const a = steps.find((s) => s.key === event.active.id), b = steps.find((s) => s.key === event.over?.id); if (!a || !b || a.phase !== b.phase) return; setSteps(arrayMove(steps, steps.indexOf(a), steps.indexOf(b))); }
  function patchSelected(patch: Partial<Step>) { setSteps((rows) => rows.map((row) => row.key === selectedKey ? { ...row, ...patch } : row)); }
  function addStep(phase: "action" | "delivery") { const type = TYPES[phase][0]; let n = steps.filter((s) => s.phase === phase).length + 1; let key = `${phase}_${n}`; while (steps.some((s) => s.key === key)) key = `${phase}_${++n}`; const config = type === "webhook.response" ? { goods_template: "Выполнено", format: "plain" } : {}; const step: Step = { key, phase, type, required: true, retry_policy: { max_attempts: 3 }, timeout_seconds: 10, config, run_before_response: pipeline?.providers.includes("digiseller") || false }; setSteps((rows) => [...rows, step].sort((a, b) => sections.indexOf(a.phase) - sections.indexOf(b.phase))); setSelectedKey(key); }
  async function save() { if (!versionId) return; await api(`/store/api/v1/pipeline-versions/${versionId}`, { method: "PUT", body: JSON.stringify({ steps }) }); toast.success("Draft saved"); await load(); }
  async function validate() { if (!versionId) return; await save(); const result = await api<{ valid: boolean; issues: { message: string }[] }>(`/store/api/v1/pipeline-versions/${versionId}/validate`, { method: "POST" }); result.valid ? toast.success("Pipeline is valid") : toast.error(result.issues.map((i) => i.message).join(" · ")); }
  async function dryRun() { if (!versionId) return; await save(); const result = await api<{ valid: boolean; sync_budget_seconds: number }>(`/store/api/v1/pipeline-versions/${versionId}/dry-run`, { method: "POST", body: JSON.stringify({ context: { order: { normalized_status: "paid", provider_order_id: "TEST-1", content_id: "CHAT-1" }, buyer: { email: "buyer@example.test" }, product: { parameters: { days: 30 } }, trigger: {}, steps: {}, system: { run_id: "dry-run", correlation_id: "dry-run" } } }) }); toast[result.valid ? "success" : "error"](`Dry run · sync ${result.sync_budget_seconds}s`); }
  async function liveTest() { if (!versionId || !confirm("Run HTTP actions against their real test integrations?")) return; await save(); const result = await api<{ executed_http_actions: number }>(`/store/api/v1/pipeline-versions/${versionId}/live-test`, { method: "POST", body: JSON.stringify({ confirmation: "LIVE TEST", context: { order: { normalized_status: "paid", provider_order_id: "LIVE-TEST-1", content_id: "LIVE-CHAT-1" }, buyer: { email: "buyer@example.test" }, product: { parameters: { days: 30 } }, trigger: { test_mode: true }, steps: {}, system: { run_id: "live-test", correlation_id: `live-${Date.now()}` } } }) }); toast.success(`Live test · ${result.executed_http_actions} HTTP action(s)`); }
  async function publish() { if (!versionId || !confirm("Publish this immutable version?")) return; const rawBindings = prompt("Binding IDs to attach (comma-separated, optional)", ""); const bindingIds = (rawBindings || "").split(",").map((value) => Number(value.trim())).filter((value) => Number.isSafeInteger(value) && value > 0); await save(); await api(`/store/api/v1/pipeline-versions/${versionId}/publish`, { method: "POST", body: JSON.stringify({ binding_ids: bindingIds }) }); toast.success("Published"); await load(); }
  async function clone() { if (!versionId) return; await api(`/store/api/v1/pipeline-versions/${versionId}/clone`, { method: "POST" }); toast.success("Draft cloned"); await load(); }
  async function rollback() { if (!versionId || !confirm("Make this published version active again for its current bindings?")) return; await api(`/store/api/v1/pipeline-versions/${versionId}/rollback`, { method: "POST", body: JSON.stringify({ binding_ids: [] }) }); toast.success("Pipeline rolled back"); await load(); }
  async function createPipeline() { const name = prompt("Pipeline name"); if (!name) return; const key = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""); const initial: Step[] = [{ key: "start", phase: "trigger", type: "trigger.conditions", required: true, retry_policy: {}, timeout_seconds: 1, config: {}, run_before_response: provider === "digiseller" }]; await api("/store/api/v1/pipelines", { method: "POST", body: JSON.stringify({ key, name, providers: [provider], steps: initial }) }); toast.success("Pipeline created"); await load(); }
  return <div className="grid min-h-[calc(100vh-7.5rem)] grid-cols-1 gap-4 xl:grid-cols-[250px_minmax(440px,1fr)_330px]">
    <Card className="min-h-0 overflow-auto p-2"><div className="flex items-center justify-between p-2"><div><h2 className="text-sm font-semibold">Catalog</h2><p className="text-xs text-muted-foreground">Pipelines & versions</p></div><Button className="h-8 w-8 px-0" onClick={createPipeline}><Plus className="h-4 w-4" /></Button></div><select className="field mx-2 mb-3 w-[calc(100%-1rem)]" value={provider} onChange={(e) => setProvider(e.target.value)}><option value="digiseller">Digiseller</option><option value="ggsel">GGSel</option></select><div className="space-y-1">{pipelines.map((row) => <button key={row.id} onClick={() => setPipelineId(row.id)} className={cn("w-full rounded-md p-3 text-left hover:bg-white/5", pipelineId === row.id && "bg-white/8")}><div className="truncate text-sm font-medium">{row.name}</div><div className="mt-1 flex gap-1">{row.providers.map((p) => <Badge key={p}>{p}</Badge>)}<span className="ml-auto text-[11px] text-muted-foreground">{row.versions.length}v</span></div></button>)}</div>{pipeline && <div className="mt-3 border-t p-2"><label className="label">Version</label><select className="field w-full" value={versionId || ""} onChange={(e) => { const id = Number(e.target.value); const v = pipeline.versions.find((x) => x.id === id); setVersionId(id); setSteps(v?.steps || []); }} >{pipeline.versions.map((v) => <option key={v.id} value={v.id}>v{v.version} · {v.status}</option>)}</select></div>}</Card>
    <Card className="min-w-0 overflow-auto p-3 md:p-5">{!pipeline ? <Empty title="Choose a pipeline" detail="Select an existing flow or create one." /> : <><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{pipeline.name}</h2><p className="muted">Linear fulfillment · immutable after publish</p></div><div className="flex flex-wrap gap-2">{isDraft ? <><Button onClick={save}><Save className="h-4 w-4" />Save</Button><Button onClick={dryRun}><TestTube2 className="h-4 w-4" />Dry run</Button><Button onClick={liveTest}><Zap className="h-4 w-4" />Live test</Button><Button onClick={validate}><Check className="h-4 w-4" />Validate</Button><Button className="button-primary" onClick={publish}><Rocket className="h-4 w-4" />Publish</Button></> : <><Button onClick={clone}><Copy className="h-4 w-4" />Clone draft</Button>{pipeline.published_version_id !== versionId && <Button onClick={rollback}><RefreshCw className="h-4 w-4" />Rollback</Button>}</>}</div></div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dragEnd}><SortableContext items={steps.map((s) => s.key)} strategy={verticalListSortingStrategy}><div className="mx-auto max-w-2xl">{sections.map((phase) => <section key={phase} className="mb-5"><div className="mb-2 flex items-center justify-between"><div className="text-[11px] font-semibold uppercase tracking-[.16em] text-muted-foreground">{phase === "trigger" ? "Start" : phase === "action" ? "Actions" : "Delivery"}</div>{phase !== "trigger" && isDraft && <Button className="h-7 border-transparent text-xs" onClick={() => addStep(phase)}><Plus className="h-3.5 w-3.5" />Add</Button>}</div><div className="space-y-2">{steps.filter((s) => s.phase === phase).map((step) => <SortableStep key={step.key} step={step} active={selectedKey === step.key} onSelect={() => setSelectedKey(step.key)} />)}</div>{phase === "action" && pipeline.providers.includes("digiseller") && <div className="my-5 flex items-center gap-3"><div className="h-px flex-1 bg-sync/35" /><div className="rounded-full border border-sync/40 bg-sync/10 px-3 py-1 text-[11px] font-medium text-sync"><Clock3 className="mr-1 inline h-3 w-3" />SYNC WALL · {syncBudget}/12s</div><div className="h-px flex-1 bg-sync/35" /></div>}</section>)}</div></SortableContext></DndContext></> }</Card>
    <Card className="min-h-0 overflow-auto">{!selected ? <Empty title="Select a step" detail="Its configuration will appear here." /> : <div className="space-y-4"><div><div className="text-xs uppercase tracking-wider text-muted-foreground">Inspector</div><h3 className="mt-1 font-semibold">{selected.key}</h3></div><label><span className="label">Key</span><Input className="w-full font-mono" disabled={!isDraft} value={selected.key} onChange={(e) => { const old = selected.key; setSteps((rows) => rows.map((row) => row.key === old ? { ...row, key: e.target.value } : row)); setSelectedKey(e.target.value); }} /></label><label><span className="label">Type</span><select className="field w-full" disabled={!isDraft || selected.phase === "trigger"} value={selected.type} onChange={(e) => patchSelected({ type: e.target.value })}>{selected.phase === "trigger" ? <option>trigger.conditions</option> : TYPES[selected.phase].map((type) => <option key={type}>{type}</option>)}</select></label><div className="grid grid-cols-2 gap-3"><label><span className="label">Timeout</span><Input type="number" disabled={!isDraft} value={selected.timeout_seconds} onChange={(e) => patchSelected({ timeout_seconds: Number(e.target.value) })} /></label><label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" disabled={!isDraft} checked={selected.required} onChange={(e) => patchSelected({ required: e.target.checked })} />Required</label></div><label className="flex gap-2 text-sm"><input type="checkbox" disabled={!isDraft} checked={selected.run_before_response} onChange={(e) => patchSelected({ run_before_response: e.target.checked })} />Before webhook response</label><label><span className="label">Idempotency key template</span><Input className="w-full font-mono text-xs" disabled={!isDraft} value={selected.idempotency_key_template || ""} onChange={(e) => patchSelected({ idempotency_key_template: e.target.value || null })} /></label><ConfigEditor step={selected} disabled={!isDraft} chips={variableChips} onChange={(config) => patchSelected({ config })} />{isDraft && selected.phase !== "trigger" && <Button className="w-full text-danger" onClick={() => { setSteps((rows) => rows.filter((row) => row.key !== selected.key)); setSelectedKey(null); }}><Trash2 className="h-4 w-4" />Remove step</Button>}</div>}</Card>
  </div>;
}
