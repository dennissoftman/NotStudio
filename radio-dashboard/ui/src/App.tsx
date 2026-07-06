import { NavLink, Route, Routes } from "react-router-dom";
import { useHealth } from "./api/hooks";
import { cx } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Backends from "./pages/Backends";
import Programs from "./pages/Programs";
import Streams from "./pages/Streams";
import Jobs from "./pages/Jobs";
import Schedules from "./pages/Schedules";
import History from "./pages/History";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/streams", label: "Streams" },
  { to: "/programs", label: "Programs" },
  { to: "/backends", label: "Backends" },
  { to: "/jobs", label: "Jobs" },
  { to: "/schedules", label: "Schedules" },
  { to: "/history", label: "History" },
];

function Sidebar() {
  const { data: health } = useHealth();
  return (
    <aside className="flex w-56 flex-col border-r border-ink-800 bg-ink-900/60 p-4">
      <div className="mb-6 flex items-center gap-2 px-1">
        <span className="text-xl">📻</span>
        <div>
          <div className="text-sm font-semibold text-slate-100">Neural Radio</div>
          <div className="text-xs text-slate-500">Control Dashboard</div>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cx(
                "rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent/20 text-accent-soft"
                  : "text-slate-400 hover:bg-ink-800 hover:text-slate-200"
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-4 space-y-1 border-t border-ink-800 pt-3 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-slate-500">API</span>
          <span className={health ? "text-emerald-400" : "text-red-400"}>
            {health ? "online" : "offline"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-500">Queue</span>
          <span className={health?.queue ? "text-emerald-400" : "text-amber-400"}>
            {health?.queue ? "ready" : "no redis"}
          </span>
        </div>
      </div>
    </aside>
  );
}

export default function App() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/streams" element={<Streams />} />
            <Route path="/programs" element={<Programs />} />
            <Route path="/backends" element={<Backends />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/schedules" element={<Schedules />} />
            <Route path="/history" element={<History />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
