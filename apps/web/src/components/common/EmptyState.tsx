import type { ReactNode } from "react";

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-2xl border border-dashed bg-slate-50 p-6 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
