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
    <header>
      <p className="text-sm font-black uppercase tracking-[0.24em] text-primary">
        {eyebrow}
      </p>
      <h1 className="mt-3 text-4xl font-black leading-none tracking-[-0.06em] text-slate-950 sm:text-5xl">
        {title}
      </h1>
      <p className="mt-4 max-w-3xl text-lg leading-8 text-muted-foreground">
        {description}
      </p>
    </header>
  );
}
