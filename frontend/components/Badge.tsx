import type { ReactNode } from "react";
import { statusTone } from "@/lib/format";

const toneClass = {
  good: "border-emerald-300 bg-emerald-50 text-emerald-800",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  blocked: "border-red-300 bg-red-50 text-red-800",
  research: "border-sky-300 bg-sky-50 text-sky-800",
  neutral: "border-stone-300 bg-stone-50 text-stone-700"
};

export function Badge({ children, tone }: { children: ReactNode; tone?: keyof typeof toneClass }) {
  const resolved = tone || statusTone(String(children));
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClass[resolved]}`}>
      {children}
    </span>
  );
}
