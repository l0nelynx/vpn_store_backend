import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, Boxes, ChevronLeft, FileClock, Gauge, GitBranch,
  Inbox, ListChecks, LogOut, Menu, MessageSquareText, Network, Package, SlidersHorizontal, X,
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

function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const nav = useNavigate();
  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex h-16 items-center gap-3 border-b px-4">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white text-xs font-bold text-black">ST</div>
        {!collapsed && (
          <div>
            <div className="text-sm font-semibold">Store Control</div>
            <div className="text-[11px] text-muted-foreground">Delivery operations</div>
          </div>
        )}
      </div>
      <nav className="flex-1 space-y-6 overflow-auto p-3">
        {groups.map((group) => (
          <div key={group.label} className="space-y-1">
            {!collapsed && (
              <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-[.14em] text-muted-foreground">
                {group.label}
              </div>
            )}
            {group.links.map(([to, label, Icon]) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                onClick={onNavigate}
                title={collapsed ? label : undefined}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-white/7 hover:text-foreground",
                    isActive && "bg-white/9 text-foreground",
                    collapsed && "justify-center px-0",
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="border-t p-3">
        <Button
          className={cn("w-full text-muted-foreground", collapsed && "px-0")}
          onClick={async () => {
            await api("/store/api/admin/logout", { method: "POST" }).catch(() => undefined);
            clearToken();
            nav("/login");
          }}
        >
          <LogOut className="h-4 w-4" />
          {!collapsed && "Log out"}
        </Button>
      </div>
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [mobileOpen]);

  return (
    <div className="flex min-h-screen bg-background">
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 overflow-hidden border-r transition-[width] md:block",
          collapsed ? "w-[68px]" : "w-[252px]",
        )}
      >
        <SidebarNav collapsed={collapsed} />
      </aside>

      <div
        className={cn(
          "fixed inset-0 z-50 md:hidden",
          mobileOpen ? "pointer-events-auto" : "pointer-events-none",
        )}
        aria-hidden={!mobileOpen}
      >
        <div
          className={cn(
            "absolute inset-0 bg-black/60 transition-opacity duration-200",
            mobileOpen ? "opacity-100" : "opacity-0",
          )}
          onClick={() => setMobileOpen(false)}
        />
        <aside
          className={cn(
            "absolute inset-y-0 left-0 h-full w-[min(18rem,88vw)] border-r bg-sidebar shadow-xl transition-transform duration-200 ease-out",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <SidebarNav collapsed={false} onNavigate={() => setMobileOpen(false)} />
        </aside>
      </div>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b bg-background/85 px-4 backdrop-blur md:px-7">
          <div className="flex items-center gap-3">
            <Button
              className="h-10 w-10 px-0 md:hidden"
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              onClick={() => setMobileOpen((v) => !v)}
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </Button>
            <Button
              className="hidden h-9 w-9 px-0 md:inline-flex"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => setCollapsed((v) => !v)}
            >
              {collapsed ? <Menu className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </Button>
            <h1 className="truncate text-sm font-semibold">{titles[location.pathname] || "Store"}</h1>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-success" />
            <span className="hidden sm:inline">PostgreSQL</span>
          </div>
        </header>
        <main className="p-4 pb-[max(1rem,env(safe-area-inset-bottom))] md:p-7">
          <div className="mx-auto max-w-[1680px]">{children}</div>
        </main>
      </div>
    </div>
  );
}

function Private({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ok" | "no">(getToken() ? "ok" : "loading");
  useEffect(() => {
    if (state === "loading") restoreSession().then((ok) => setState(ok ? "ok" : "no"));
  }, [state]);
  if (state === "loading") {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Restoring session…</div>;
  }
  if (state === "no") return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

function AppToaster() {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const sync = () => setNarrow(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return <Toaster theme="dark" richColors position={narrow ? "bottom-center" : "bottom-right"} />;
}

export default function App() {
  return (
    <>
      <Suspense
        fallback={
          <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">
            Loading workspace…
          </div>
        }
      >
        <Routes>
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
        </Routes>
      </Suspense>
      <AppToaster />
    </>
  );
}
