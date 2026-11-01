import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./session";
import Shell from "./Shell";
import Audit from "./pages/Audit";
import Board from "./pages/Board";
import Import from "./pages/Import";
import Login from "./pages/Login";
import RunDetail from "./pages/RunDetail";
import Runs from "./pages/Runs";
import ScheduleDetail from "./pages/ScheduleDetail";
import ScheduleForm from "./pages/ScheduleForm";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import TaskDetail from "./pages/TaskDetail";
import Tasks from "./pages/Tasks";
import Workers from "./pages/Workers";

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

function NotFound() {
  return <p className="font-mono text-sm text-ink-2">nothing here.</p>;
}

export default function App() {
  const { status } = useSession();
  return (
    <Routes>
      <Route path="/setup" element={status === "setup" ? <Setup /> : <Navigate to="/" replace />} />
      <Route path="/login" element={status === "ready" ? <Navigate to="/" replace /> : <Login />} />
      <Route
        element={
          <Gate>
            <Shell />
          </Gate>
        }
      >
        <Route index element={<Board />} />
        <Route path="schedules/new" element={<ScheduleForm />} />
        <Route path="schedules/:name" element={<ScheduleDetail />} />
        <Route path="schedules/:name/edit" element={<ScheduleForm />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<RunDetail />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="tasks/:name" element={<TaskDetail />} />
        <Route path="workers" element={<Workers />} />
        <Route path="import" element={<Import />} />
        <Route path="audit" element={<Audit />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
