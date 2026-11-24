import Link from "next/link";

export default function HomePage() {
  return (
    <div className="relative min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between">
      {/* Background radial gradients for subtle enterprise lighting */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[700px] h-[350px] bg-gradient-to-b from-blue-600/15 via-blue-900/5 to-transparent blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-[400px] h-[300px] bg-sky-500/10 blur-3xl" />
      </div>

      {/* Navigation Header */}
      <header className="relative z-10 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center font-bold text-blue-400">
              L
            </div>
            <div>
              <span className="font-semibold tracking-tight text-white text-base">
                LeadGen Platform
              </span>
              <span className="ml-2 text-xs font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60">
                Phase 1 MVP
              </span>
            </div>
          </div>
          <div className="flex items-center space-x-3 text-xs">
            <Link
              href="/login"
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors"
            >
              Sign In
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <main className="relative z-10 max-w-6xl mx-auto px-6 py-20 flex-1 flex flex-col justify-center">
        <div className="max-w-3xl">
          <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-blue-950/60 border border-blue-800/50 text-blue-300 text-xs font-medium mb-6">
            <span>Residential HVAC Lead Intelligence</span>
            <span className="text-slate-500">|</span>
            <span className="text-slate-400 font-normal">Autonomous Qualification & Booking</span>
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-white leading-tight">
            Convert incoming HVAC leads into booked appointments, autonomously.
          </h1>

          <p className="mt-6 text-lg text-slate-400 leading-relaxed max-w-2xl">
            A high-reliability conversational platform combining deterministic qualification rules,
            AI interpretation, and transactional scheduling to eliminate missed customer opportunities.
          </p>

          <div className="mt-10 flex flex-wrap gap-4 items-center">
            <Link
              href="/dashboard"
              className="px-5 py-2.5 rounded-lg bg-blue-600 text-white font-medium text-sm hover:bg-blue-500 transition-colors shadow-sm shadow-blue-500/20"
            >
              Launch Operations Dashboard &rarr;
            </Link>
            <Link
              href="/login"
              className="px-5 py-2.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white font-medium text-sm transition-colors"
            >
              Sign In / Demo Accounts
            </Link>
          </div>
        </div>

        {/* Feature Grid */}
        <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-6 rounded-xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
            <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4 font-bold text-sm">
              01
            </div>
            <h3 className="text-base font-semibold text-white">Deterministic Qualification</h3>
            <p className="mt-2 text-sm text-slate-400 leading-relaxed">
              Rules-backed validation for service zones, heating/cooling equipment, and immediate
              safety escalations (gas leak, CO, smoke).
            </p>
          </div>

          <div className="p-6 rounded-xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
            <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4 font-bold text-sm">
              02
            </div>
            <h3 className="text-base font-semibold text-white">Transactional Outbox</h3>
            <p className="mt-2 text-sm text-slate-400 leading-relaxed">
              Atomic event persistence guaranteeing zero lost webhook events between the FastAPI core
              and n8n automation engine.
            </p>
          </div>

          <div className="p-6 rounded-xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
            <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4 font-bold text-sm">
              03
            </div>
            <h3 className="text-base font-semibold text-white">Multi-Tenant Isolation</h3>
            <p className="mt-2 text-sm text-slate-400 leading-relaxed">
              Strict organization-level boundaries enforced across PostgreSQL models, database
              constraints, and API authorization tokens.
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-slate-800/80 bg-slate-950/60 py-6 text-center text-xs text-slate-500">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <span>Project LeadGen — HVAC Lead Conversion Platform (Dev Environment)</span>
          <span className="font-mono text-slate-400">Node v22.23.2 | Next.js 16 | React 19</span>
        </div>
      </footer>
    </div>
  );
}
