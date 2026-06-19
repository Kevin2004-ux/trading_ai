export function WarningBox({ title = "Paper trading only", items }: { title?: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="rounded-3xl border border-amber-200 bg-amber-50/90 p-4 text-amber-950">
      <div className="font-bold">{title}</div>
      <ul className="mt-2 space-y-1 text-sm">
        {items.map((item) => (
          <li key={item}>- {item}</li>
        ))}
      </ul>
    </div>
  );
}
