"use client";

import React, { useEffect, useState } from "react";
import {
  BarChart3,
  TrendingUp,
  Flame,
  ShieldAlert,
  Users,
  Filter,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";

export default function AnalyticsPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const res = await api.analytics.get();
        setData(res);
        setError(null);
      } catch (err: any) {
        setError(err.message || "Failed to load analytics");
      } finally {
        setLoading(false);
      }
    };
    fetchAnalytics();
  }, []);

  return (
    <DashboardLayout>
      <Header
        title="Conversion Funnel & Lead Quality Analytics"
        subtitle="Real PostgreSQL aggregated performance metrics, triage breakdown, and customer response distributions"
      />

      <div className="p-6 space-y-6 max-w-5xl">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {loading ? (
          <div className="py-12 text-center text-xs text-slate-500">Aggregating database statistics...</div>
        ) : (
          <div className="space-y-6">
            {/* Conversion Funnel */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider pb-2 border-b border-slate-800">
                Lead Intake Lifecycle Funnel
              </h3>

              <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                {[
                  { label: "New", key: "NEW", color: "text-amber-400 bg-amber-950/40 border-amber-800" },
                  { label: "Contacted", key: "CONTACTED", color: "text-indigo-400 bg-indigo-950/40 border-indigo-800" },
                  { label: "Qualified", key: "QUALIFIED", color: "text-blue-400 bg-blue-950/40 border-blue-800" },
                  { label: "Offered", key: "APPOINTMENT_OFFERED", color: "text-cyan-400 bg-cyan-950/40 border-cyan-800" },
                  { label: "Booked", key: "APPOINTMENT_BOOKED", color: "text-emerald-400 bg-emerald-950/40 border-emerald-800" },
                  { label: "Unqualified", key: "UNQUALIFIED", color: "text-slate-400 bg-slate-800/40 border-slate-700" },
                ].map((step) => (
                  <div key={step.key} className={`border rounded-xl p-3 text-center ${step.color}`}>
                    <span className="text-[11px] font-medium opacity-80">{step.label}</span>
                    <p className="text-2xl font-bold mt-1">{data?.funnel?.[step.key] || 0}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Urgency & Qualification Category Breakdown */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Urgency Distribution */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider pb-2 border-b border-slate-800">
                  Customer Urgency Tiers
                </h3>
                <div className="space-y-2.5">
                  {[
                    { label: "EMERGENCY (Immediate)", key: "EMERGENCY", color: "bg-red-500", text: "text-red-400" },
                    { label: "HIGH (Today)", key: "HIGH", color: "bg-orange-500", text: "text-orange-400" },
                    { label: "MEDIUM (1-2 Days)", key: "MEDIUM", color: "bg-blue-500", text: "text-blue-400" },
                    { label: "LOW (Next Week)", key: "LOW", color: "bg-slate-500", text: "text-slate-400" },
                  ].map((item) => {
                    const count = data?.urgency_breakdown?.[item.key] || 0;
                    return (
                      <div key={item.key} className="flex items-center justify-between text-xs">
                        <span className={`font-medium ${item.text}`}>{item.label}</span>
                        <span className="font-bold text-white bg-slate-950 px-2.5 py-1 rounded border border-slate-800">
                          {count}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Qualification Categories */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider pb-2 border-b border-slate-800">
                  Qualification Engine Tiers
                </h3>
                <div className="space-y-2.5">
                  {[
                    { label: "HOT (Immediate Conversion)", key: "HOT", text: "text-orange-400" },
                    { label: "WARM (Routine Service Area)", key: "WARM", text: "text-emerald-400" },
                    { label: "HUMAN_REVIEW (Complex / Hazard)", key: "HUMAN_REVIEW", text: "text-amber-400" },
                    { label: "COLD (Out of Area / Scope)", key: "COLD", text: "text-slate-400" },
                  ].map((item) => {
                    const count = data?.qualification_breakdown?.[item.key] || 0;
                    return (
                      <div key={item.key} className="flex items-center justify-between text-xs">
                        <span className={`font-medium ${item.text}`}>{item.label}</span>
                        <span className="font-bold text-white bg-slate-950 px-2.5 py-1 rounded border border-slate-800">
                          {count}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
