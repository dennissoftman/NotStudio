import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useHealth } from "./api/hooks";
import { cx } from "./components/ui";
import Generate from "./pages/Generate";
import Library from "./pages/Library";

const NAV = [
  { to: "/", label: "Generate", end: true },
  { to: "/library", label: "Review" },
];

function Sidebar() {
  const { data: health } = useHealth();
  return (
    <aside className="flex w-52 flex-col border-r border-ink-800 bg-ink-900/60 p-4">
      <div className="mb-6 flex items-center gap-2 px-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/20 text-sm font-semibold text-accent-soft">
          N
        </span>
        <div>
          <div className="text-sm font-semibold text-slate-100">Not Studio</div>
          <div className="text-xs text-slate-500">Music and taste</div>
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
                  : "text-slate-400 hover:bg-ink-800 hover:text-slate-200",
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
          <span className="text-slate-500">Jobs</span>
          <span className={health ? "text-emerald-400" : "text-amber-400"}>
            {health?.jobs ?? "offline"}
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
        <div className="mx-auto max-w-5xl p-6">
          <Routes>
            <Route path="/" element={<Generate />} />
            <Route path="/library" element={<Library />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
