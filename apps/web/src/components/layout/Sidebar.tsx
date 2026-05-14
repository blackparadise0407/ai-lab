import type { ComponentType } from "react";
import { BriefcaseBusiness, LayoutDashboard, Plug, UploadCloud, Video } from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "../../lib/utils";
import { Badge } from "../ui/badge";

const navigationItems: {
  path: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  end?: boolean;
}[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { path: "/connector", label: "Connector", icon: Plug },
  { path: "/jobs", label: "Jobs", icon: BriefcaseBusiness },
  { path: "/publish", label: "Publish", icon: UploadCloud },
  { path: "/videos", label: "Videos", icon: Video },
];

export function Sidebar() {
  return (
    <aside className="relative overflow-hidden border-b border-white/10 bg-slate-950 px-4 py-4 text-white shadow-2xl shadow-slate-950/20 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r lg:border-white/10 lg:px-5 lg:py-6">
      <div className="absolute inset-x-0 top-0 h-40 bg-[radial-gradient(circle_at_top_left,rgba(99,102,241,0.34),transparent_58%)] lg:w-full" />
      <div className="relative flex items-center justify-between gap-4 lg:block">
        <div>
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-2xl bg-white text-sm font-black text-primary shadow-lg shadow-primary/30">
              AI
            </span>
            <div>
              <p className="text-xs font-black uppercase tracking-[0.24em] text-cyan-200">
                AI Lab
              </p>
              <h2 className="mt-1 text-xl font-black tracking-[-0.04em] text-white">
                Short Videos
              </h2>
            </div>
          </div>
        </div>
        <Badge variant="secondary" className="border-white/10 bg-white/10 text-cyan-100 lg:mt-5">
          AI SaaS
        </Badge>
      </div>

      <nav className="relative mt-5 flex gap-2 overflow-x-auto lg:grid lg:gap-2 lg:overflow-visible">
        {navigationItems.map((item) => {
          const Icon = item.icon;

          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex min-w-max items-center gap-3 rounded-2xl border border-transparent px-4 py-3 text-sm font-bold text-slate-300 transition hover:border-white/10 hover:bg-white/10 hover:text-white lg:min-w-0",
                  isActive &&
                    "border-white/20 bg-white text-slate-950 shadow-xl shadow-primary/20 hover:bg-white hover:text-slate-950",
                )
              }
            >
              <Icon className="size-4" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>

      <div className="relative mt-8 hidden rounded-3xl border border-white/10 bg-white/[0.06] p-4 text-sm text-slate-300 shadow-2xl shadow-black/20 lg:block">
        <p className="font-bold text-white">Production workflow</p>
        <p className="mt-2 leading-6">
          Translate, dub, publish, and monitor AI video pipelines from one polished command center.
        </p>
      </div>
    </aside>
  );
}
