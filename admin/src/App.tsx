import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, Boxes, ChartNoAxesCombined, ChevronLeft, FileClock, Gauge, GitBranch,
  Inbox, ListChecks, LogOut, Menu, MessageSquareText, Network, Package, Settings2, SlidersHorizontal, X,
} from "lucide-react";
import { Toaster } from "sonner";
import { api, clearToken, getToken, restoreSession } from "./api";
import { Button, cn } from "./components/ui";
const LoginPage = lazy(() => import("./pages/LoginPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const ProductsPage = lazy(() => import("./pages/ProductsPage"));
const OrdersPage = lazy(() => import("./pages/OrdersPage"));
const CustomerPage = lazy(() => import("./pages/CustomerPage"));
const InboxPage = lazy(() => import("./pages/InboxPage"));
const ParametersPage = lazy(() => import("./pages/ParametersPage"));
const MappingsPage = lazy(() => import("./pages/MappingsPage"));
const PipelinesPage = lazy(() => import("./pages/PipelinesPage"));
const RunsPage = lazy(() => import("./pages/RunsPage"));
const TemplatesPage = lazy(() => import("./pages/TemplatesPage"));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));

const groups = [
  { label: "Operate", links: [
    ["/", "Dashboard", Gauge], ["/orders", "Orders", ListChecks], ["/runs", "Runs", Activity], ["/inbox", "Inbox", Inbox],
  ]},
  { label: "Configure", links: [
    ["/products", "Products", Package], ["/pipelines", "Pipelines", GitBranch], ["/templates", "Templates", MessageSquareText],
    ["/parameters", "Parameters", SlidersHorizontal], ["/value-mappings", "Mappings", Boxes],
  ]},
  { label: "System", links: [
    ["/integrations", "Integrations", Network], ["/audit", "Audit", FileClock],
  ]},
] as const;

const titles: Record<string, string> = {
  "/": "Dashboard", "/products": "Products", "/pipelines": "Delivery Pipelines",
  "/orders": "Orders", "/runs": "Pipeline Runs", "/inbox": "Inbox",
  "/templates": "Message Templates", "/parameters": "Parameters",
  "/value-mappings": "Value Mappings", "/integrations": "Integration Health", "/audit": "Audit Log",
};

function Shell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const location = useLocation(); const nav = useNavigate();
  const sidebar = <div className="flex h-full flex-col bg-sidebar">
    <div className="flex h-16 items-center gap-3 border-b px-4">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white text-xs font-bold text-black">ST</div>
      {!collapsed && <div><div className="text-sm font-semibold">Store Control</div><div className="text-[11px] text-muted-foreground">Delivery operations</div></div>}
    </div>
    <nav className="flex-1 space-y-6 overflow-auto p-3">
      {groups.map((group) => <div key={group.label} className="space-y-1">
        {!collapsed && <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-[.14em] text-muted-foreground">{group.label}</div>}
        {group.links.map(([to, label, Icon]) => <NavLink key={to} to={to} end={to === "/"} onClick={() => setMobile(false)}
          title={collapsed ? label : undefined}
          className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-white/7 hover:text-foreground", isActive && "bg-white/9 text-foreground", collapsed && "justify-center px-0")}>
          <Icon className="h-4 w-4 shrink-0" />{!collapsed && <span>{label}</span>}
        </NavLink>)}
      </div>)}
    </nav>
    <div className="border-t p-3"><Button className={cn("w-full text-muted-foreground", collapsed && "px-0")} onClick={async () => {
      await api("/store/api/admin/logout", { method: "POST" }).catch(() => undefined); clearToken(); nav("/login");
    }}><LogOut className="h-4 w-4" />{!collapsed && "Log out"}</Button></div>
  </div>;
  return <div className="flex min-h-screen bg-background">
    <aside className={cn("sticky top-0 hidden h-screen shrink-0 overflow-hidden border-r transition-[width] md:block", collapsed ? "w-[68px]" : "w-[252px]")}>{sidebar}</aside>
    {mobile && <div className="fixed inset-0 z-40 bg-black/60 md:hidden" onClick={() => setMobile(false)}><aside className="h-full w-72" onClick={(e) => e.stopPropagation()}>{sidebar}</aside></div>}
    <div className="min-w-0 flex-1">
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b bg-background/85 px-4 backdrop-blur md:px-7">
        <div className="flex items-center gap-3"><Button className="h-9 w-9 px-0" onClick={() => window.innerWidth < 768 ? setMobile(true) : setCollapsed(!collapsed)}>{mobile ? <X className="h-4 w-4" /> : collapsed ? <Menu className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}</Button><h1 className="text-sm font-semibold">{titles[location.pathname] || "Store"}</h1></div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-success" />PostgreSQL</div>
      </header>
      <main className="p-4 md:p-7"><div className="mx-auto max-w-[1680px]">{children}</div></main>
    </div>
  </div>;
}

function Private({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ok" | "no">(getToken() ? "ok" : "loading");
  useEffect(() => { if (state === "loading") restoreSession().then((ok) => setState(ok ? "ok" : "no")); }, [state]);
  if (state === "loading") return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Restoring session…</div>;
  if (state === "no") return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return <><Suspense fallback={<div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading workspace…</div>}><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/" element={<Private><DashboardPage /></Private>} />
    <Route path="/products" element={<Private><ProductsPage /></Private>} />
    <Route path="/pipelines" element={<Private><PipelinesPage /></Private>} />
    <Route path="/orders" element={<Private><OrdersPage /></Private>} />
    <Route path="/runs" element={<Private><RunsPage /></Private>} />
    <Route path="/customers/:id" element={<Private><CustomerPage /></Private>} />
    <Route path="/inbox" element={<Private><InboxPage /></Private>} />
    <Route path="/templates" element={<Private><TemplatesPage /></Private>} />
    <Route path="/parameters" element={<Private><ParametersPage /></Private>} />
    <Route path="/mappings" element={<Navigate to="/parameters" replace />} />
    <Route path="/value-mappings" element={<Private><MappingsPage /></Private>} />
    <Route path="/integrations" element={<Private><IntegrationsPage /></Private>} />
    <Route path="/audit" element={<Private><AuditPage /></Private>} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></Suspense><Toaster theme="dark" richColors position="bottom-right" /></>;
}
