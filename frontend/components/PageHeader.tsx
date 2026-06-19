export function PageHeader({
  eyebrow,
  title,
  description
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="mb-6 rounded-[2rem] bg-ink p-6 text-white shadow-card">
      <div className="text-xs font-bold uppercase tracking-[0.28em] text-amberline">{eyebrow}</div>
      <h1 className="mt-3 text-4xl font-black leading-tight md:text-5xl">{title}</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-stone-200">{description}</p>
    </header>
  );
}
