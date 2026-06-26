"use client";

import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, asRecord, pickNested } from "@/lib/api";
import { fmt } from "@/lib/format";
import { normalizeChatResponse, NormalizedChatResponse } from "@/lib/tradingTypes";
import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { WarningBox } from "@/components/WarningBox";
import { AssistantResultPanel } from "@/components/ideas/AssistantResultPanel";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  response?: NormalizedChatResponse;
}

const suggestedPrompts = [
  "What is the best swing trade now?",
  "Give me your best stocks.",
  "Give me your best options.",
  "Review AAPL.",
  "What should I watch?",
  "Why did nothing pass?",
  "What is broken in my setup?",
  "How are the paper trades performing?"
];

function nowStamp(): string {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function hasTradeIdeaPayload(response?: NormalizedChatResponse): boolean {
  if (!response) return false;
  const assistant = response.assistant;
  const rowCount = assistant.top_stocks.length + assistant.top_options.length + assistant.option_underlying_watchlist.length + assistant.paper_eligible.length;
  return assistant.response_type === "trade_ideas" || assistant.ranking_status === "unavailable" || rowCount > 0;
}

function loadingLabel(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("option")) return "Building options research response...";
  if (normalized.includes("review ")) return "Reviewing ticker...";
  if (normalized.includes("health") || normalized.includes("broken") || normalized.includes("setup")) return "Checking system state...";
  return "Planning scan...";
}

export function ChatExperience({ compactHeader = false }: { compactHeader?: boolean }) {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [input, setInput] = useState("Give me your best available stock ideas right now. Do stock only. Include watchlist and blocked-but-interesting ideas, but do not include options.");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Ask for stock ideas, option research, ticker reviews, paper-trade performance, or setup health. I’ll use the deterministic backend as source of truth and label paper-only status clearly.",
      timestamp: nowStamp()
    }
  ]);
  const [loading, setLoading] = useState(false);
  const [activeLabel, setActiveLabel] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    apiGet("/api/status", { timeoutMs: 30000 }).then(setStatus);
    return () => abortRef.current?.abort();
  }, []);

  const providerStatus = fmt(pickNested(status, "readiness.readiness"), status?.ok ? "online" : "checking");
  const plannerProvider = fmt(status?.ai_planner_provider, status?.gemini_available ? "OpenAI planner" : "deterministic fallback");
  const optionStatus = fmt(pickNested(status, "readiness.categories.options_ready.status"), fmt(status?.option_discovery_status, "options gated"));
  const learning = asRecord(status?.learning);
  const statusWarnings = useMemo(() => {
    const warnings = Array.isArray(status?.warnings) ? (status?.warnings as string[]) : [];
    return warnings.slice(0, 3);
  }, [status]);

  async function submit(text = input) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      timestamp: nowStamp()
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setLoading(true);
    setActiveLabel(loadingLabel(trimmed));
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const payload = await apiPost("/api/chat", { message: trimmed }, { signal: controller.signal, timeoutMs: 120000 });
    const normalized = normalizeChatResponse(payload);
    setMessages((current) => [
      ...current,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: normalized.answer,
        timestamp: nowStamp(),
        response: normalized
      }
    ]);
    setLoading(false);
    setActiveLabel("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="space-y-6">
      <header className={`overflow-hidden rounded-[2rem] bg-ink p-6 text-white shadow-card ${compactHeader ? "" : "md:p-8"}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.28em] text-amberline">Trading research assistant</div>
            <h1 className="mt-3 max-w-3xl text-4xl font-black leading-tight md:text-6xl">Ask for the best idea. See the gates.</h1>
            <p className="mt-4 max-w-3xl text-sm leading-6 text-stone-200">
              Chat-first paper-trading research. The backend ranks candidates, constraints decide eligibility, and the frontend explains the result without brokerage execution.
            </p>
          </div>
          <div className="grid min-w-64 gap-2 text-sm">
            <Badge tone="neutral">Paper trading only</Badge>
            <Badge tone={status?.ok ? "good" : "warning"}>Backend {providerStatus}</Badge>
            <Badge tone={plannerProvider.toLowerCase().includes("openai") ? "good" : "research"}>{plannerProvider}</Badge>
            <Badge tone={optionStatus.toLowerCase().includes("ready") ? "good" : "research"}>Options {optionStatus}</Badge>
          </div>
        </div>
      </header>

      {statusWarnings.length ? <WarningBox title="Current setup notices" items={statusWarnings} /> : null}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="rounded-[2rem] border border-white/70 bg-white/70 p-4 shadow-card backdrop-blur md:p-5">
          <div className="max-h-[68vh] space-y-4 overflow-y-auto pr-1" aria-live="polite">
            {messages.map((message) => (
              <article key={message.id} className={message.role === "user" ? "ml-auto max-w-3xl" : "max-w-5xl"}>
                <div className={`rounded-[1.6rem] p-4 shadow-sm ${message.role === "user" ? "bg-ink text-white" : "bg-white/85 text-ink"}`}>
                  <div className="mb-2 flex items-center justify-between gap-3 text-xs font-bold uppercase tracking-[0.16em] opacity-70">
                    <span>{message.role === "user" ? "You" : "Assistant"}</span>
                    <time>{message.timestamp}</time>
                  </div>
                  <div className="whitespace-pre-wrap text-sm leading-7">{message.content}</div>
                </div>
                {hasTradeIdeaPayload(message.response) ? (
                  <div className="mt-4">
                    <AssistantResultPanel response={message.response} assistant={message.response.assistant} raw={message.response.raw} />
                  </div>
                ) : message.response ? (
                  <div className="mt-3 rounded-3xl border border-stone-200 bg-white/70 p-4">
                    <JsonPanel title="Advanced diagnostics" data={message.response.raw} />
                  </div>
                ) : null}
              </article>
            ))}
            {loading ? (
              <div className="rounded-[1.6rem] bg-white/85 p-4 text-sm font-bold text-stone-700" aria-live="assertive">
                {activeLabel || "Building response..."}
              </div>
            ) : null}
          </div>

          <div className="mt-5 rounded-[1.6rem] border border-stone-200 bg-stone-50/80 p-3">
            <label htmlFor="chat-input" className="sr-only">Ask the trading research assistant</label>
            <textarea
              id="chat-input"
              className="min-h-28 w-full resize-y rounded-2xl border border-stone-200 bg-white p-4 text-sm outline-none focus:border-tide focus:ring-2 focus:ring-tide"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              placeholder="Ask for best stocks, options research, AAPL review, system health, or paper-trade performance..."
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-stone-600">Enter sends. Shift+Enter adds a newline.</p>
              <button
                className="rounded-2xl bg-ink px-5 py-3 font-black text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-tide"
                onClick={() => submit()}
                disabled={loading || !input.trim()}
                type="button"
              >
                {loading ? "Running..." : "Ask assistant"}
              </button>
            </div>
          </div>
        </div>

        <aside className="space-y-4">
          <section className="rounded-[2rem] border border-white/70 bg-white/70 p-5 shadow-card">
            <h2 className="text-lg font-black">Suggested prompts</h2>
            <div className="mt-4 grid gap-2">
              {suggestedPrompts.map((prompt) => (
                <button
                  key={prompt}
                  className="rounded-2xl bg-stone-50 px-4 py-3 text-left text-sm font-bold text-stone-800 transition hover:bg-ink hover:text-white focus:outline-none focus:ring-2 focus:ring-tide"
                  onClick={() => submit(prompt)}
                  disabled={loading}
                  type="button"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-[2rem] border border-white/70 bg-white/70 p-5 shadow-card">
            <h2 className="text-lg font-black">Paper safety</h2>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-stone-700">
              <li>- No brokerage execution routes.</li>
              <li>- Chat never sends auto-log requests.</li>
              <li>- Gemini cannot override deterministic gates.</li>
              <li>- Blocked/watchlist rows stay visibly non-final.</li>
            </ul>
          </section>

          <section className="rounded-[2rem] border border-white/70 bg-white/70 p-5 shadow-card">
            <h2 className="text-lg font-black">Learning status</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <div><dt className="font-bold">State</dt><dd>{fmt(learning.status, "collecting data")}</dd></div>
              <div><dt className="font-bold">Active policy</dt><dd className="break-all">{fmt(learning.active_policy_version)}</dd></div>
              <div><dt className="font-bold">Snapshots</dt><dd>{fmt(learning.candidate_snapshot_count)}</dd></div>
            </dl>
          </section>
        </aside>
      </section>
    </div>
  );
}
