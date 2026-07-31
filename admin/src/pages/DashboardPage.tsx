import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDollarSign, PackageCheck, Workflow } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Badge, Card, Select } from "../components/ui";

type Overview = {
  orders: number;
  delivered: number;
  gross_rub: number;
  net_rub: number;
  needs_review: number;
  dead_letters: number;
  digiseller_p95_seconds: number | null;
  providers: { provider: string; orders: number }[];
};
type Health = {
  database: { ok: boolean };
  ggsel: { ok?: boolean };
  digiseller: { ok?: boolean };
  outbox?: Record<string, number>;
};
type SeriesPoint = { bucket: string; ggsel: number; digiseller: number };
type SeriesResponse = { range: string; metric: string; series: SeriesPoint[] };

type RangeKey = "day" | "week" | "month" | "3m" | "6m" | "year";
type MetricKey = "orders" | "revenue";

const RANGE_OPTIONS: Array<{ value: RangeKey; label: string }> = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "3m", label: "3 months" },
  { value: "6m", label: "6 months" },
  { value: "year", label: "Year" },
];

const METRIC_OPTIONS: Array<{ value: MetricKey; label: string }> = [
  { value: "orders", label: "Orders" },
  { value: "revenue", label: "Revenue" },
];

const GGSEL_COLOR = "var(--success)";
const DIGISELLER_COLOR = "var(--sync)";

function money(value?: number) {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function formatBucket(value: string, range: RangeKey) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  if (range === "day") {
    return date.toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }
  if (range === "year") {
    return date.toLocaleString("ru-RU", { month: "short", year: "2-digit" });
  }
  if (range === "3m" || range === "6m") {
    return date.toLocaleString("ru-RU", { day: "2-digit", month: "short" });
  }
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "short" });
}

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [range, setRange] = useState<RangeKey>("week");
  const [metric, setMetric] = useState<MetricKey>("orders");
  const [series, setSeries] = useState<SeriesPoint[]>([]);

  useEffect(() => {
    Promise.all([
      api<Overview>("/store/api/v1/analytics/overview"),
      api<Health>("/store/api/v1/integration-health"),
    ]).then(([a, h]) => {
      setData(a);
      setHealth(h);
    });
  }, []);

  useEffect(() => {
    const qs = new URLSearchParams({ range, metric });
    api<SeriesResponse>(`/store/api/v1/analytics/series?${qs}`)
      .then((res) => setSeries(res.series || []))
      .catch(() => setSeries([]));
  }, [range, metric]);

  const chartData = useMemo(
    () =>
      series.map((point) => ({
        ...point,
        label: formatBucket(point.bucket, range),
      })),
    [series, range],
  );

  const cards = [
    ["Orders", data?.orders || 0, PackageCheck],
    ["Delivered", data?.delivered || 0, CheckCircle2],
    ["Gross", money(data?.gross_rub), CircleDollarSign],
    ["Net proceeds", money(data?.net_rub), Workflow],
  ] as const;

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Fulfillment desk</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
            Every delivery, one operational timeline.
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={health?.ggsel.ok ? "success" : "danger"}>GGSel</Badge>
          <Badge tone={health?.digiseller.ok ? "success" : "danger"}>Digiseller</Badge>
          <Badge tone={health?.database.ok ? "success" : "danger"}>PostgreSQL</Badge>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value, Icon]) => (
          <Card key={label}>
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
              <Icon className="h-4 w-4" />
            </div>
            <div className="mt-5 text-2xl font-semibold tabular-nums">{value}</div>
          </Card>
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card className="min-w-0">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="font-medium">Sales by platform</h3>
              <p className="muted">Stacked {metric === "revenue" ? "revenue" : "orders"} over the selected window.</p>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: GGSEL_COLOR }} />
                  ggsel
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: DIGISELLER_COLOR }} />
                  digiseller
                </span>
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Select
                aria-label="Time range"
                className="sm:w-36"
                value={range}
                onValueChange={(value) => setRange(value as RangeKey)}
                options={RANGE_OPTIONS}
              />
              <Select
                aria-label="Metric"
                className="sm:w-36"
                value={metric}
                onValueChange={(value) => setMetric(value as MetricKey)}
                options={METRIC_OPTIONS}
              />
            </div>
          </div>
          <div className="h-60 w-full min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid vertical={false} stroke="rgba(255,255,255,.08)" />
                <XAxis
                  dataKey="label"
                  axisLine={false}
                  tickLine={false}
                  minTickGap={24}
                  tick={{ fill: "rgba(255,255,255,.55)", fontSize: 12 }}
                />
                <YAxis
                  width={48}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "rgba(255,255,255,.55)", fontSize: 12 }}
                  tickFormatter={(value: number) =>
                    metric === "revenue"
                      ? new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(value)
                      : String(value)
                  }
                />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,.04)" }}
                  contentStyle={{
                    background: "#242424",
                    border: "1px solid rgba(255,255,255,.14)",
                    borderRadius: 10,
                  }}
                  labelStyle={{ color: "rgba(255,255,255,.7)" }}
                  formatter={(value, name) => {
                    const amount = typeof value === "number" ? value : Number(value || 0);
                    const label = String(name);
                    return [metric === "revenue" ? money(amount) : amount, label];
                  }}
                />
                <Bar dataKey="ggsel" name="ggsel" stackId="sales" fill={GGSEL_COLOR} radius={[0, 0, 0, 0]} />
                <Bar dataKey="digiseller" name="digiseller" stackId="sales" fill={DIGISELLER_COLOR} radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <h3 className="font-medium">Attention queue</h3>
          <p className="muted mt-1">Runs that need an operator decision.</p>
          <div className="mt-6 space-y-3">
            <div className="flex items-center justify-between rounded-md border p-3">
              <span className="flex items-center gap-2 text-sm">
                <AlertTriangle className="h-4 w-4 text-warning" />
                Needs review
              </span>
              <b>{data?.needs_review || 0}</b>
            </div>
            <div className="flex items-center justify-between rounded-md border p-3">
              <span className="text-sm">Dead letter</span>
              <b>{data?.dead_letters || 0}</b>
            </div>
            <div className="flex items-center justify-between rounded-md border p-3">
              <span className="text-sm">Pending outbox</span>
              <b>{health?.outbox?.pending || 0}</b>
            </div>
            <div className="flex items-center justify-between rounded-md border p-3">
              <span className="text-sm">Digiseller sync p95 / 12s</span>
              <b className={(data?.digiseller_p95_seconds || 0) > 12 ? "text-danger" : "text-success"}>
                {data?.digiseller_p95_seconds == null ? "—" : `${Number(data.digiseller_p95_seconds).toFixed(1)}s`}
              </b>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
