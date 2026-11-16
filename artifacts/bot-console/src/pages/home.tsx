import { useHealthCheck, getHealthCheckQueryKey } from "@workspace/api-client-react";
import { RefreshCw, Mic, Cpu, FileText, Send, Server, AlertTriangle, CheckCircle2, XCircle, HelpCircle } from "lucide-react";

const commands = [
  { cmd: "/start", desc: "Opens a session and explains what the bot expects: voice notes in Hebrew and site photos." },
  { cmd: "/report", desc: "Closes collection and generates the RTL Word report from everything sent so far." },
  { cmd: "/clear", desc: "Discards the collected voice notes and photos so you can start a fresh inspection." },
  { cmd: "/help", desc: "Shows the command list and short usage reminders inside Telegram." },
];

const stages = [
  { icon: Mic, title: "Prepare media", desc: "Voice notes and photos are downloaded and readied for analysis." },
  { icon: Cpu, title: "Analyze", desc: "Hebrew speech and images are interpreted into structured findings." },
  { icon: FileText, title: "Build Word", desc: "A right-to-left .docx report is assembled with the findings and photos." },
  { icon: Send, title: "Send", desc: "The finished document is delivered back in the same Telegram chat." },
];

const hosting = [
  "Use one Reserved VM instance. The bot polls Telegram continuously, so it needs a process that stays running.",
  "Run only one Telegram poller at a time. Two pollers on the same bot token conflict and drop updates.",
  "Let reports in progress finish before switching versions or stopping the development copy.",
  "Check Publishing settings and confirm production secrets are set before publishing.",
  "Publishing requires confirmation from the project owner.",
];

function ApiStatus() {
  const q = useHealthCheck({ query: { queryKey: getHealthCheckQueryKey(), refetchInterval: 30_000 } });
  const ok = q.isSuccess && q.data?.status === "ok";
  const state = q.isLoading ? "checking" : q.isError ? "unreachable" : ok ? "reachable" : "unexpected";
  const tone =
    state === "reachable" ? "bg-[hsl(150_40%_36%)]" : state === "checking" ? "bg-muted-foreground" : "bg-destructive";
  const Icon = state === "reachable" ? CheckCircle2 : state === "checking" ? HelpCircle : XCircle;
  const label = {
    checking: "Checking API...",
    reachable: "API reachable",
    unreachable: "API not reachable",
    unexpected: `API responded: ${q.data?.status ?? "unknown"}`,
  }[state];

  return (
    <section className="rise rounded-lg border-2 border-foreground bg-card shadow-[4px_4px_0_hsl(var(--foreground))]" data-testid="panel-api-status">
      <div className="flex items-center justify-between gap-3 border-b-2 border-foreground px-4 py-2 font-mono text-[11px] uppercase tracking-widest">
        <span>Sheet A-01 / Connectivity</span>
        <span className="text-muted-foreground">auto 30s</span>
      </div>
      <div className="p-4">
        {q.isLoading ? (
          <div className="space-y-2">
            <div className="h-6 w-40 animate-pulse rounded bg-muted" />
            <div className="h-4 w-56 animate-pulse rounded bg-muted" />
          </div>
        ) : (
          <div className="flex items-start gap-3">
            <span className="relative mt-2 flex h-3 w-3 shrink-0">
              <span className={`absolute inset-0 rounded-full ${tone} ${state === "reachable" ? "pulse-dot" : ""}`} />
              <span className={`relative h-3 w-3 rounded-full ${tone}`} />
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-xl font-extrabold" data-testid="status-api">
                <Icon className="h-5 w-5" /> {label}
              </p>
              <p className="mt-1 font-mono text-xs text-muted-foreground" data-testid="text-last-checked">
                {q.isError
                  ? "The health endpoint did not answer. The API server may be stopped or restarting."
                  : q.dataUpdatedAt
                    ? `Last checked ${new Date(q.dataUpdatedAt).toLocaleTimeString()}`
                    : ""}
              </p>
            </div>
          </div>
        )}
        <button
          onClick={() => q.refetch()}
          disabled={q.isFetching}
          data-testid="button-refresh-health"
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-transform hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${q.isFetching ? "animate-spin" : ""}`} />
          {q.isFetching ? "Checking" : q.isError ? "Retry" : "Check now"}
        </button>
        <div className="mt-4 flex gap-2 rounded-md border border-dashed border-primary bg-primary/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <p>
            <strong>API reachable is not the same as bot online.</strong> This check only confirms the API server answers. It does
            not verify the Telegram connection or Gemini. To confirm the bot, send <span className="font-mono">/help</span> to it in Telegram.
          </p>
        </div>
      </div>
    </section>
  );
}

function SectionHead({ n, title }: { n: string; title: string }) {
  return (
    <h2 className="mb-3 flex items-baseline gap-3 text-lg font-extrabold">
      <span className="font-mono text-xs text-primary">{n}</span>
      {title}
      <span className="h-px flex-1 translate-y-[-4px] bg-border" />
    </h2>
  );
}

export default function Home() {
  return (
    <div className="blueprint min-h-[100dvh]">
      <div className="hazard h-2" />
      <main className="mx-auto max-w-2xl space-y-10 px-4 py-8 sm:py-12">
        <header className="rise">
          <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-accent">Operating guide</p>
          <h1 className="mt-2 text-4xl font-extrabold leading-none tracking-tight sm:text-5xl">
            EnigmaTech<span className="text-primary">.</span>
          </h1>
          <p className="mt-3 max-w-lg text-muted-foreground">
            A Telegram bot for construction inspectors. Send Hebrew voice notes and site photos; get back a right-to-left Word report.
          </p>
          <p className="mt-2 text-right font-semibold text-accent" dir="rtl" lang="he">דוח פיקוח בקול ובתמונה</p>
        </header>

        <ApiStatus />

        <section>
          <SectionHead n="02" title="Commands" />
          <ul className="divide-y divide-border rounded-lg border border-border bg-card">
            {commands.map((c) => (
              <li key={c.cmd} className="flex gap-4 px-4 py-3 transition-colors hover:bg-secondary/60" data-testid={`row-command-${c.cmd.slice(1)}`}>
                <code className="w-16 shrink-0 font-mono text-sm font-semibold text-primary">{c.cmd}</code>
                <span className="text-sm">{c.desc}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <SectionHead n="03" title="How a report is made" />
          <ol className="relative space-y-3 border-l-2 border-dashed border-accent/50 pl-6">
            {stages.map((s, i) => (
              <li key={s.title} className="group relative" data-testid={`stage-${i + 1}`}>
                <span className="absolute -left-[33px] top-2 flex h-4 w-4 items-center justify-center rounded-sm bg-accent font-mono text-[9px] text-accent-foreground transition-transform group-hover:scale-125">
                  {i + 1}
                </span>
                <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-3 transition-transform group-hover:translate-x-1">
                  <s.icon className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
                  <div>
                    <p className="font-semibold">{s.title}</p>
                    <p className="text-sm text-muted-foreground">{s.desc}</p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section>
          <SectionHead n="04" title="Hosting checklist" />
          <div className="rounded-lg bg-foreground p-4 text-background">
            <p className="mb-3 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-primary">
              <Server className="h-4 w-4" /> Before publishing
            </p>
            <ul className="space-y-2.5">
              {hosting.map((h, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="font-mono text-primary">{String(i + 1).padStart(2, "0")}</span>
                  <span>{h}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 border-t border-background/20 pt-3 text-xs text-background/70">
              This page does not indicate that the bot is published or continuously online.
            </p>
          </div>
        </section>

        <footer className="pb-4 font-mono text-[11px] text-muted-foreground">EnigmaTech / inspection reports via Telegram</footer>
      </main>
    </div>
  );
}
