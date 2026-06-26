"use client";

import { useState } from "react";

export function JsonPanel({ title = "Raw JSON", data }: { title?: string; data: unknown }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const payload = JSON.stringify(data, null, 2);
  async function copyPayload() {
    try {
      await navigator.clipboard.writeText(payload);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="rounded-2xl border border-stone-200 bg-white/55 text-stone-700">
      <button
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-semibold text-ink focus:outline-none focus:ring-2 focus:ring-tide"
        onClick={() => setOpen((value) => !value)}
        type="button"
        aria-expanded={open}
      >
        <span>{title}</span>
        <span>{open ? "Hide" : "Show"}</span>
      </button>
      {open ? (
        <div className="border-t border-stone-200">
          <div className="flex justify-end p-3">
            <button
              className="rounded-full border border-stone-300 bg-white px-3 py-1 text-xs font-bold text-stone-700 hover:bg-stone-100 focus:outline-none focus:ring-2 focus:ring-tide"
              onClick={copyPayload}
              type="button"
            >
              {copied ? "Copied" : "Copy JSON"}
            </button>
          </div>
          <pre className="max-h-96 overflow-auto px-4 pb-4 text-xs leading-relaxed text-stone-700">
            {payload}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
