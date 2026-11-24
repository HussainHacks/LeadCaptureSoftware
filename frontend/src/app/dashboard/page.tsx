"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Users,
  MessageSquare,
  Calendar,
  Flame,
  AlertTriangle,
  TrendingUp,
  ArrowRight,
  ShieldAlert,
  Clock,
  CheckCircle2,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";

export default function DashboardPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = async () => {
    try {
      const res = await api.dashboard.get();
      setData(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  return (
    <DashboardLayout>
      <Header
        title="Contractor Operations Dashboard"
        subtitle="Real-time HVAC lead triage, automated conversation tracking, and appointments"
      />

      <div className="p-6 space-y-6">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {/* 1. Critical Safety Escalation Alert Banner */}
        {data?.safety_alerts && data.safety_alerts.length > 0 && (
          <div className="bg-red-950/80 border-2 border-red-600 rounded-xl p-4 shadow-lg shadow-red-950/50 animate-pulse">
            <div className="flex items-start space-x-3">
              <div className="p-2 bg-red-600 rounded-lg text-white shrink-0">
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-red-200 uppercase tracking-wider">
                    Immediate Safety Alert — Automated Replies Locked
                  </h3>
                  <span className="text-[11px] bg-red-900 text-red-300 font-semibold px-2 py-0.5 rounded-full">
                    {data.safety_alerts.length} Critical Event
                  </span>
                </div>
                <p className="text-xs text-red-300 mt-1">
                  A potential safety hazard (gas leak, CO, electrical smoke) has been detected in a
                  customer conversation. Automated messages are locked to protect customer safety.
                </p>

                <div className="mt-3 space-y-2">
                  {data.safety_alerts.map((alert: any) => (
                    <div
                      key={alert.conversation_id}
                      className="bg-slate-950/70 border border-red-800/80 rounded-lg p-2.5 flex items-center justify-between"
                    >
                      <div>
                        <p className="text-xs font-semibold text-white">
                          {alert.customer_name} ({alert.phone})
                        </p>
                        <p className="text-[11px] text-red-400 italic font-mono truncate max-w-xl">
                          "{alert.problem_description}"
                        </p>
                      </div>
                      <Link
                        href={`/conversations/${alert.conversation_id}`}
                        className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white text-xs font-semibold rounded-md shadow transition-colors flex items-center space-x-1"
                      >
                        <span>Take Over & Review</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 2. Key Metrics KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Total Leads</span>
              <Users className="w-4 h-4 text-blue-400" />
            </div>
            <p className="text-2xl font-bold text-white mt-2">
              {loading ? "..." : data?.kpis?.total_leads ?? 0}
            </p>
            <span className="text-[10px] text-slate-500">All inbound inquiries</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">New Leads</span>
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
            </div>
            <p className="text-2xl font-bold text-amber-400 mt-2">
              {loading ? "..." : data?.kpis?.new_leads ?? 0}
            </p>
            <span className="text-[10px] text-slate-500">Pending initial response</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Qualified</span>
              <Flame className="w-4 h-4 text-orange-400" />
            </div>
            <p className="text-2xl font-bold text-orange-400 mt-2">
              {loading ? "..." : data?.kpis?.qualified_leads ?? 0}
            </p>
            <span className="text-[10px] text-slate-500">Service area & scope verified</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Active Chats</span>
              <MessageSquare className="w-4 h-4 text-indigo-400" />
            </div>
            <p className="text-2xl font-bold text-indigo-400 mt-2">
              {loading ? "..." : data?.kpis?.active_conversations ?? 0}
            </p>
            <span className="text-[10px] text-slate-500">Simulated AI / Staff</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Booked Appts</span>
              <Calendar className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-2xl font-bold text-emerald-400 mt-2">
              {loading ? "..." : data?.kpis?.confirmed_appointments ?? 0}
            </p>
            <span className="text-[10px] text-slate-500">Capacity confirmed</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Conversion</span>
              <TrendingUp className="w-4 h-4 text-cyan-400" />
            </div>
            <p className="text-2xl font-bold text-cyan-400 mt-2">
              {loading ? "..." : `${data?.kpis?.conversion_rate_percent ?? 0}%`}
            </p>
            <span className="text-[10px] text-slate-500">Lead to Appointment</span>
          </div>
        </div>

        {/* 3. Operational Two-Column Overview */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Recent Leads */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-xs font-semibold text-slate-200 uppercase tracking-wider">
                Recent Inbound Leads
              </h3>
              <Link href="/leads" className="text-xs text-blue-400 hover:underline flex items-center space-x-1">
                <span>View all leads</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="mt-3 divide-y divide-slate-800/60">
              {data?.recent_leads && data.recent_leads.length > 0 ? (
                data.recent_leads.map((lead: any) => (
                  <div key={lead.id} className="py-3 flex items-center justify-between">
                    <div>
                      <div className="flex items-center space-x-2">
                        <p className="text-xs font-semibold text-white">
                          {lead.first_name} {lead.last_name}
                        </p>
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                            lead.urgency === "HIGH" || lead.urgency === "EMERGENCY"
                              ? "bg-red-950 text-red-400 border border-red-800"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {lead.urgency}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono">
                          {lead.postal_code || "No ZIP"}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 mt-0.5 truncate max-w-sm">
                        {lead.service_type || "HVAC Diagnostic"}
                      </p>
                    </div>

                    <Link
                      href={`/leads/${lead.id}`}
                      className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px] text-slate-300 transition-colors"
                    >
                      Details
                    </Link>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 py-6 text-center">No leads captured yet.</p>
              )}
            </div>
          </div>

          {/* Upcoming Appointments */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-xs font-semibold text-slate-200 uppercase tracking-wider">
                Upcoming Dispatch Schedule
              </h3>
              <Link href="/appointments" className="text-xs text-blue-400 hover:underline flex items-center space-x-1">
                <span>View calendar</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="mt-3 divide-y divide-slate-800/60">
              {data?.upcoming_appointments && data.upcoming_appointments.length > 0 ? (
                data.upcoming_appointments.map((appt: any) => (
                  <div key={appt.id} className="py-3 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-white">{appt.customer_name}</p>
                      <p className="text-[11px] text-slate-400 mt-0.5">{appt.service_name}</p>
                      <div className="flex items-center space-x-1.5 text-[10px] text-blue-400 mt-1">
                        <Clock className="w-3 h-3" />
                        <span>{new Date(appt.start).toLocaleString()}</span>
                      </div>
                    </div>

                    <span className="text-[10px] px-2.5 py-1 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-400 font-medium">
                      {appt.status}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 py-6 text-center">No appointments scheduled.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
