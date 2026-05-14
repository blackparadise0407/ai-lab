import type { ReactNode } from "react";

export function EmptyState({
  children,
  message,
}: {
  children?: ReactNode;
  message?: ReactNode;
}) {
  return (
    <p className="rounded-2xl border border-dashed bg-card/70 p-6 text-center text-sm text-muted-foreground shadow-sm backdrop-blur">
      {children ?? message}
    </p>
  );
}
