"use client";

import React, { useState } from "react";
import { AlertTriangle, RefreshCw, Sparkles, Send } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

interface HeaderProps {
  title: string;
  subtitle?: string;
  actionButton?: React.ReactNode;
}

export function Header({ title, subtitle, actionButton }: HeaderProps) {
  const { activeOrg } = useAuth();
  const canSweep = ["owner", "admin"].includes(activeOrg?.role || "");
  const [isSweeping, setIsSweeping] = useState(false);
  const [sweepMsg, setSweepMsg] = useState<string | null>(null);

  const handleSweepOutbox = async () => {
    setIsSweeping(true);
    setSweepMsg(null);
    try {
      const res = await api.outbox.sweep();
      setSweepMsg(`Processed ${res.processed_events} events (${res.recovered_leases} recovered)`);
      setTimeout(() => setSweepMsg(null), 4000);
    } catch (err: any) {
      setSweepMsg(`Sweep error: ${err.message}`);
      setTimeout(() => setSweepMsg(null), 4000);
    } finally {
      setIsSweeping(false);
    }
  };

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-30">
      <div>
        <h2 className="text-base font-semibold text-white tracking-tight">{title}</h2>
        {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
      </div>

      <div className="flex items-center space-x-3">
        {sweepMsg && (
          <span className="text-xs text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-2.5 py-1 rounded-full animate-fade-in">
            {sweepMsg}
          </span>
        )}

        {/* Outbox manual sweep button (Owner/Admin only) */}
        {canSweep && (
          <button
            onClick={handleSweepOutbox}
            disabled={isSweeping}
            title="Manually process pending outbox events (simulated dispatcher)"
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs text-slate-300 font-medium transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSweeping ? "animate-spin text-blue-400" : ""}`} />
            <span>Outbox Sweep (Simulated)</span>
          </button>
        )}

        {actionButton}
      </div>
    </header>
  );
}
