import Link from "next/link";
import type { ReactNode } from "react";

interface LegalPageLayoutProps {
  title: string;
  summary: string;
  children: ReactNode;
}

export function LegalPageLayout({
  title,
  summary,
  children,
}: LegalPageLayoutProps) {
  return (
    <main className="min-h-screen bg-[radial-gradient(ellipse_at_top,_rgba(8,145,178,0.12),_transparent_48%),#090D18] px-4 py-8 text-slate-100 sm:px-6 sm:py-12">
      <div className="mx-auto max-w-4xl">
        <nav
          aria-label="Legal navigation"
          className="mb-8 flex flex-wrap items-center justify-between gap-4"
        >
          <Link href="/" className="text-sm font-bold tracking-wide text-white hover:text-cyan-200">
            ClassMate AI
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <Link href="/terms" className="text-slate-300 underline-offset-4 hover:text-cyan-200 hover:underline">
              Terms of Use
            </Link>
            <Link href="/privacy" className="text-slate-300 underline-offset-4 hover:text-cyan-200 hover:underline">
              Privacy Policy
            </Link>
          </div>
        </nav>

        <header className="rounded-3xl border border-cyan-500/20 bg-[#111A2B]/90 p-6 shadow-2xl shadow-cyan-950/20 sm:p-10">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            ClassMate AI · Version 2026-11-08
          </p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            {title}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300">{summary}</p>
          <div
            role="note"
            className="mt-6 rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm leading-6 text-amber-100"
          >
            <strong>Owner confirmation required before paid launch.</strong> The codebase
            does not identify the legal operator, a monitored support contact, the
            governing forum, or a confirmed hosting/data-region configuration. Those
            details and the service-specific refund procedure must be confirmed and
            published; this draft is not lawyer-reviewed.
          </div>
        </header>

        <article className="mt-6 space-y-5 rounded-3xl border border-slate-800 bg-[#0F1728]/95 p-6 shadow-xl sm:p-10">
          {children}
          <section className="border-t border-slate-800 pt-6">
            <h2 className="text-lg font-semibold text-white">Related information</h2>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
              <Link href="/terms" className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200">
                Terms of Use
              </Link>
              <Link href="/privacy" className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200">
                Privacy Policy
              </Link>
              <Link href="/" className="text-slate-300 underline underline-offset-4 hover:text-white">
                Return to ClassMate AI
              </Link>
            </div>
          </section>
          <p className="border-t border-slate-800 pt-5 text-xs leading-5 text-slate-500">
            Version 2026-11-08 · Published for owner and qualified legal review before
            commercial launch.
          </p>
        </article>
      </div>
    </main>
  );
}

export function LegalSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="scroll-mt-6">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-7 text-slate-300">{children}</div>
    </section>
  );
}
