import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDollarSign, PackageCheck, Workflow } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { api } from "../api";
import { Badge, Card } from "../components/ui";

type Overview = { orders: number; delivered: number; gross_rub: number; net_rub: number; needs_review: number; dead_letters: number; digiseller_p95_seconds: number | null; providers: { provider: string; orders: number }[] };
type Health = { database: { ok: boolean }; ggsel: { ok?: boolean }; digiseller: { ok?: boolean }; outbox?: Record<string, number> };

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null); const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => { Promise.all([api<Overview>("/store/api/v1/analytics/overview"), api<Health>("/store/api/v1/integration-health")]).then(([a, h]) => { setData(a); setHealth(h); }); }, []);
  const money = (value?: number) => new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(value || 0);
  const cards = [
    ["Orders", data?.orders || 0, PackageCheck], ["Delivered", data?.delivered || 0, CheckCircle2],
    ["Gross", money(data?.gross_rub), CircleDollarSign], ["Net proceeds", money(data?.net_rub), Workflow],
  ] as const;
  return <div className="space-y-6">
    <section className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Fulfillment desk</p><h2 className="mt-2 text-2xl font-semibold tracking-tight">Every delivery, one operational timeline.</h2></div><div className="flex gap-2"><Badge tone={health?.ggsel.ok ? "success" : "danger"}>GGSel</Badge><Badge tone={health?.digiseller.ok ? "success" : "danger"}>Digiseller</Badge><Badge tone={health?.database.ok ? "success" : "danger"}>PostgreSQL</Badge></div></section>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label, value, Icon]) => <Card key={label}><div className="flex items-center justify-between text-muted-foreground"><span className="text-xs font-medium uppercase tracking-wide">{label}</span><Icon className="h-4 w-4" /></div><div className="mt-5 text-2xl font-semibold tabular-nums">{value}</div></Card>)}</section>
    <section className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
      <Card><div className="mb-5"><h3 className="font-medium">Orders by provider</h3><p className="muted">Imported and delivered orders in the current ledger.</p></div><div className="h-60"><ResponsiveContainer><BarChart data={data?.providers || []}><XAxis dataKey="provider" axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: "rgba(255,255,255,.04)" }} contentStyle={{ background: "#242424", border: "1px solid rgba(255,255,255,.14)", borderRadius: 10 }} /><Bar dataKey="orders" fill="rgba(255,255,255,.78)" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
      <Card><h3 className="font-medium">Attention queue</h3><p className="muted mt-1">Runs that need an operator decision.</p><div className="mt-6 space-y-3"><div className="flex items-center justify-between rounded-md border p-3"><span className="flex items-center gap-2 text-sm"><AlertTriangle className="h-4 w-4 text-warning" />Needs review</span><b>{data?.needs_review || 0}</b></div><div className="flex items-center justify-between rounded-md border p-3"><span className="text-sm">Dead letter</span><b>{data?.dead_letters || 0}</b></div><div className="flex items-center justify-between rounded-md border p-3"><span className="text-sm">Pending outbox</span><b>{health?.outbox?.pending || 0}</b></div><div className="flex items-center justify-between rounded-md border p-3"><span className="text-sm">Digiseller p95 / 12s</span><b className={(data?.digiseller_p95_seconds || 0) > 12 ? "text-danger" : "text-success"}>{data?.digiseller_p95_seconds == null ? "—" : `${Number(data.digiseller_p95_seconds).toFixed(1)}s`}</b></div></div></Card>
    </section>
  </div>;
}
