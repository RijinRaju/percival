import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./session";
import Login from "./pages/Login";
import Setup from "./pages/Setup";

function Gate({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const location = useLocation();
  if (status === "loading") return <p className="p-8 font-mono text-sm text-ink-2">loading…</p>;
  if (status === "setup") return <Navigate to="/setup" replace />;
  if (status === "anonymous") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const { status } = useSession();
  return (
    <Routes>
      <Route path="/setup" element={status === "setup" ? <Setup /> : <Navigate to="/" replace />} />
      <Route path="/login" element={status === "ready" ? <Navigate to="/" replace /> : <Login />} />
      <Route
        path="*"
        element={
          <Gate>
            <p className="p-8 font-mono">logged in</p>
          </Gate>
        }
      />
    </Routes>
  );
}
