import type { ComponentType } from "react";
import { LayoutDashboard, Plug, Video } from "lucide-react";

import type { AppPage } from "../../interfaces/navigation";
import { cn } from "../../lib/utils";
import { Badge } from "../ui/badge";

const navigationItems: {
  page: AppPage;
  label: string;
  icon: ComponentType<{ className?: string }>;
}[] = [
  { page: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { page: "connector", label: "Connector", icon: Plug },
  { page: "videos", label: "Videos", icon: Video },
];

export function Sidebar({
  activePage,
  onPageChange,
}: {
  activePage: AppPage;
  onPageChange: (page: AppPage) => void;
}) {
  return (
    <aside className="border-b border-border/70 bg-white/85 px-4 py-4 shadow-xl shadow-slate-900/5 backdrop-blur lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r lg:px-5 lg:py-6">
      <div className="flex items-center justify-between gap-4 lg:block">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.24em] text-primary">
            AI Lab
          </p>
          <h2 className="mt-2 text-xl font-black tracking-[-0.04em] text-slate-950">
            Short Videos
          </h2>
        </div>
        <Badge variant="secondary" className="lg:mt-4">
          Draft
        </Badge>
      </div>

      <nav className="mt-5 flex gap-2 overflow-x-auto lg:grid lg:gap-2 lg:overflow-visible">
        {navigationItems.map((item) => {
          const Icon = item.icon;
          const isActive = activePage === item.page;

          return (
            <button
              key={item.page}
              type="button"
              className={cn(
                "flex min-w-max items-center gap-3 rounded-2xl px-4 py-3 text-sm font-bold text-muted-foreground transition hover:bg-primary/10 hover:text-primary lg:min-w-0",
                isActive &&
                  "bg-primary text-primary-foreground shadow-lg shadow-primary/20 hover:bg-primary hover:text-primary-foreground",
              )}
              onClick={() => onPageChange(item.page)}
            >
              <Icon className="size-4" />
              {item.label}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
