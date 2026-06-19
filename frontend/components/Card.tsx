import type { ReactNode } from "react";

export function Card({
  title,
  value,
  detail,
  children
}: {
  title: string;
  value?: ReactNode;
  detail?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-white/70 bg-white/75 p-5 shadow-card backdrop-blur">
      <div className="text-xs font-bold uppercase tracking-[0.22em] text-moss">{title}</div>
      {value !== undefined ? <div className="mt-3 text-3xl font-black text-ink">{value}</div> : null}
      {detail ? <div className="mt-2 text-sm text-stone-600">{detail}</div> : null}
      {children ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}
