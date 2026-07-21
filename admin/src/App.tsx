import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, clearToken, getToken } from "./api";
import LoginPage from "./pages/LoginPage";
import ProductsPage from "./pages/ProductsPage";
import OrdersPage from "./pages/OrdersPage";
import CustomerPage from "./pages/CustomerPage";
import InboxPage from "./pages/InboxPage";
import ParametersPage from "./pages/ParametersPage";
import MappingsPage from "./pages/MappingsPage";

function Shell({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  return (
    <div className="layout">
      <aside className="nav">
        <h1>Store Admin</h1>
        <NavLink to="/" end>Products</NavLink>
        <NavLink to="/parameters">Parameters</NavLink>
        <NavLink to="/value-mappings">Mappings</NavLink>
        <NavLink to="/orders">Orders</NavLink>
        <NavLink to="/inbox">Inbox</NavLink>
        <button
          style={{ marginTop: "1.5rem", width: "100%" }}
          onClick={async () => {
            try {
              await api("/store/api/admin/logout", { method: "POST" });
            } catch {
              /* ignore */
            }
            clearToken();
            nav("/login");
          }}
        >
          Log out
        </button>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

function Private({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Private><ProductsPage /></Private>} />
      <Route path="/parameters" element={<Private><ParametersPage /></Private>} />
      <Route path="/mappings" element={<Navigate to="/parameters" replace />} />
      <Route path="/value-mappings" element={<Private><MappingsPage /></Private>} />
      <Route path="/orders" element={<Private><OrdersPage /></Private>} />
      <Route path="/customers/:id" element={<Private><CustomerPage /></Private>} />
      <Route path="/inbox" element={<Private><InboxPage /></Private>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
