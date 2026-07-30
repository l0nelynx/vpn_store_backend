import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, Clock3, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { Badge, Button, Card, Empty } from "../components/ui";

type Run = {
  id: number; order_id: number; pipeline_version_id: number; status: string;
  correlation_id: string; error_code: string | null; created_at: string;
};
type StepAttempt = {
  id: number; step_id: number; step_key: string; type: string; status: string;
  attempt: number; outputs: object; error_detail: string | null;
};
type Detail = Run & { context: object; steps: StepAttempt[] };

const tone = (status: string) => status.startsWith("delivered")
  ? "success"
  : status === "needs_review" || status === "failed" ? "danger" : "warning";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [status, setStatus] = useState("");
  const load = () => api<Run[]>(`/store/api/v1/pipeline-runs${status ? `?status=${status}` : ""}`).then(setRuns);
  useEffect(() => { load(); }, [status]);

  async function open(id: number) {
    setSelected(await api<Detail>(`/store/api/v1/pipeline-runs/${id}`));
  }
  async function retry(stepId: number) {
    if (!selected) return;
    await api(`/store/api/v1/pipeline-runs/${selected.id}/steps/${stepId}/retry`, { method: "POST" });
    toast.success("Retry queued");
    await open(selected.id);
  }

  return <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_430px]">
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div><h2 className="page-title">Pipeline runs</h2><p className="muted mt-1">Every attempt and output stays attached to its immutable version.</p></div>
        <div className="flex gap-2">
          <select className="field" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All states</option><option value="pending">Pending</option>
            <option value="needs_review">Needs review</option><option value="delivered">Delivered</option>
          </select>
          <Button onClick={load}><RefreshCw className="h-4 w-4" /></Button>
        </div>
      </div>
      <Card className="overflow-x-auto p-0"><table><thead><tr>
        <th>Run</th><th>Order</th><th>Status</th><th>Correlation</th><th>Started</th><th />
      </tr></thead><tbody>{runs.map((run) => <tr key={run.id}>
        <td className="font-mono">#{run.id}</td><td>#{run.order_id}</td>
        <td><Badge tone={tone(run.status) as "success" | "danger" | "warning"}>{run.status}</Badge></td>
        <td className="max-w-52 truncate font-mono text-xs text-muted-foreground">{run.correlation_id}</td>
        <td>{new Date(run.created_at).toLocaleString()}</td>
        <td><Button className="h-8 w-8 px-0" onClick={() => open(run.id)}><ChevronRight className="h-4 w-4" /></Button></td>
      </tr>)}</tbody></table></Card>
    </div>
    <Card className="min-h-[420px]">{!selected
      ? <Empty title="Select a run" detail="Step attempts and outputs will appear here." />
      : <div>
        <div className="flex items-start justify-between">
          <div><p className="text-xs uppercase tracking-wider text-muted-foreground">Run #{selected.id}</p><h3 className="mt-1 font-semibold">Order #{selected.order_id}</h3></div>
          <Badge tone={tone(selected.status) as "success" | "danger" | "warning"}>{selected.status}</Badge>
        </div>
        <div className="mt-6 space-y-0">{selected.steps.map((step, index) => <div key={step.id} className="relative flex gap-3 pb-6">
          <div className="flex flex-col items-center">
            <span className={`grid h-7 w-7 place-items-center rounded-full border ${step.status === "succeeded" ? "text-success" : step.status === "failed" ? "text-danger" : "text-warning"}`}>
              {step.status === "succeeded" ? <CheckCircle2 className="h-4 w-4" /> : step.status === "failed" ? <AlertTriangle className="h-4 w-4" /> : <Clock3 className="h-4 w-4" />}
            </span>
            {index < selected.steps.length - 1 && <span className="w-px flex-1 bg-border" />}
          </div>
          <div className="min-w-0 flex-1 pt-1">
            <div className="flex justify-between gap-2">
              <div><div className="text-sm font-medium">{step.step_key}</div><code className="text-[11px] text-muted-foreground">{step.type} · attempt {step.attempt}</code></div>
              {step.status === "failed" && <Button className="h-8" onClick={() => retry(step.step_id)}><RotateCcw className="h-3.5 w-3.5" />Retry</Button>}
            </div>
            {Object.keys(step.outputs || {}).length > 0 && <pre className="mt-2 max-h-32 overflow-auto rounded-md bg-black/25 p-2 text-[11px] text-muted-foreground">{JSON.stringify(step.outputs, null, 2)}</pre>}
            {step.error_detail && <p className="error mt-2">{step.error_detail}</p>}
          </div>
        </div>)}</div>
      </div>}
    </Card>
  </div>;
}
