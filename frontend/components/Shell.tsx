import type { ReactNode } from "react";
import Link from "next/link";
import { Badge } from "@/components/Badge";

const primaryNav = [
  ["/", "Chat"],
  ["/ideas", "Ideas"],
  ["/trades", "Paper Trades"],
  ["/system", "System"]
];

const advancedNav = [
  ["/chat", "Chat route"],
  ["/scan", "Scan controls"],
  ["/options", "Options lab"],
  ["/performance", "Performance"],
  ["/reports", "Reports"]
];

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="fixed inset-0 -z-10 bg-[radial-gradient(circle_at_15%_20%,rgba(181,107,69,0.20),transparent_28%),radial-gradient(circle_at_88%_5%,rgba(45,111,115,0.20),transparent_28%),linear-gradient(135deg,#f6f0e4,#eef2df_45%,#f7eadb)]" />
      <aside className="fixed left-4 top-4 hidden h-[calc(100vh-2rem)] w-64 rounded-[2rem] border border-white/70 bg-white/70 p-5 shadow-card backdrop-blur xl:block">
        <div className="text-2xl font-black tracking-tight">Trading AI</div>
        <p className="mt-2 text-sm text-stone-600">Chat-first paper-trading research assistant.</p>
        <div className="mt-4">
          <Badge tone="neutral">No brokerage execution</Badge>
        </div>
        <nav className="mt-8 space-y-2">
          {primaryNav.map(([href, label]) => (
            <Link key={href} href={href} className="block rounded-2xl px-4 py-3 text-sm font-bold text-stone-700 transition hover:bg-ink hover:text-white">
              {label}
            </Link>
          ))}
        </nav>
        <div className="mt-8 border-t border-stone-200 pt-5">
          <div className="text-xs font-black uppercase tracking-[0.22em] text-moss">Advanced</div>
          <nav className="mt-3 space-y-1">
            {advancedNav.map(([href, label]) => (
              <Link key={href} href={href} className="block rounded-xl px-3 py-2 text-xs font-bold text-stone-500 transition hover:bg-stone-100 hover:text-ink">
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </aside>
      <main className="mx-auto max-w-7xl px-4 py-5 xl:ml-72 xl:mr-8">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-white/70 bg-white/65 px-5 py-4 shadow-card backdrop-blur">
          <div>
            <div className="text-sm font-bold uppercase tracking-[0.25em] text-clay">Trading research assistant</div>
            <div className="text-xs text-stone-600">Backend remains source of truth. Chat explains structured paper-only results.</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral">Paper only</Badge>
            <Badge tone="research">Options gated</Badge>
            <Badge tone="good">SQLite truth</Badge>
          </div>
        </div>
        <div className="xl:hidden">
          <nav className="mb-5 flex gap-2 overflow-x-auto pb-2">
            {[...primaryNav, ...advancedNav].map(([href, label]) => (
              <Link key={href} href={href} className="shrink-0 rounded-full bg-white/80 px-4 py-2 text-sm font-bold shadow">
                {label}
              </Link>
            ))}
          </nav>
        </div>
        {children}
      </main>
    </div>
  );
}
