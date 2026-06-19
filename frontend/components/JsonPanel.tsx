"use client";

import { useState } from "react";

export function JsonPanel({ title = "Raw JSON", data }: { title?: string; data: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-stone-200 bg-white/70">
      <button
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-ink"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span>{title}</span>
        <span>{open ? "Hide" : "Show"}</span>
      </button>
      {open ? (
        <pre className="max-h-96 overflow-auto border-t border-stone-200 p-4 text-xs leading-relaxed text-stone-700">
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
