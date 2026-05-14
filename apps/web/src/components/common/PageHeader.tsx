export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="relative overflow-hidden rounded-[2rem] border bg-card/80 p-6 shadow-2xl shadow-slate-950/5 backdrop-blur sm:p-8">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(79,70,229,0.14),transparent_42%)]" />
      <div className="relative">
        <p className="text-sm font-black uppercase tracking-[0.24em] text-primary">
          {eyebrow}
        </p>
        <h1 className="mt-3 text-4xl font-black leading-none tracking-[-0.06em] text-slate-950 sm:text-5xl">
          {title}
        </h1>
        <p className="mt-4 max-w-3xl text-lg leading-8 text-muted-foreground">
          {description}
        </p>
      </div>
    </header>
  );
}
