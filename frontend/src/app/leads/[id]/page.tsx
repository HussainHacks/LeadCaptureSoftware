"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Users,
  MessageSquare,
  Calendar,
  Flame,
  ShieldAlert,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Phone,
  Mail,
  MapPin,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

function LeadDetailContent() {
  const params = useParams();
  const router = useRouter();
  const { activeOrg } = useAuth();
  const leadId = params?.id as string;

  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [qualifying, setQualifying] = useState(false);

  const canManage = ["owner", "admin", "dispatcher"].includes(activeOrg?.role || "");

  const fetchLead = async () => {
    try {
      const res = await api.leads.get(leadId);
      setDetail(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load lead profile");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (leadId) fetchLead();
  }, [leadId]);

  const handleStatusChange = async (newStatus: string) => {
    setStatusUpdating(true);
    try {
      await api.leads.updateStatus(leadId, newStatus);
      fetchLead();
    } catch (err: any) {
      setError(err.message || "Failed to update lead status");
    } finally {
      setStatusUpdating(false);
    }
  };

  const handleRunQualification = async () => {
    setQualifying(true);
    setError(null);
    try {
      await api.leads.qualify(leadId);
      await fetchLead();
    } catch (err: any) {
      setError(err.message || "Failed to run qualification");
    } finally {
      setQualifying(false);
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-xs text-slate-500">Loading lead profile...</div>
      </DashboardLayout>
    );
  }

  if (!detail || !detail.lead) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-xs text-red-400">
          {error || "Lead not found"}
        </div>
      </DashboardLayout>
    );
  }

  const lead = detail.lead;
  const qualification = detail.qualification;

  return (
    <DashboardLayout>
      <Header
        title={`${lead.first_name || ""} ${lead.last_name || ""}`.trim() || "Unnamed Customer"}
        subtitle={`Inbound Lead ID: ${lead.id}`}
        actionButton={
          <div className="flex items-center space-x-2">
            <Link
              href="/leads"
              className="flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Leads</span>
            </Link>
            {detail.conversation_id && (
              <Link
                href={`/conversations/${detail.conversation_id}`}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white font-semibold shadow"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>Open Chat Thread</span>
              </Link>
            )}
          </div>
        }
      />

      <div className="p-6 space-y-6 max-w-5xl">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {/* Profile Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Customer & Inquiry Details */}
          <div className="md:col-span-2 space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider pb-2 border-b border-slate-800">
                Customer & Service Requirements
              </h3>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-[11px] text-slate-500">Full Name</span>
                  <p className="text-sm font-semibold text-white">
                    {lead.first_name} {lead.last_name}
                  </p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500">Phone Number</span>
                  <p className="text-sm font-mono text-slate-200">{lead.phone}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500">Email Address</span>
                  <p className="text-sm text-slate-200">{lead.email || "None provided"}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500">Service Location</span>
                  <p className="text-sm text-slate-200">
                    {lead.street_address || "No Street"}, ZIP: {lead.postal_code || "Unknown"}
                  </p>
                </div>
              </div>

              <div className="pt-3 border-t border-slate-800">
                <span className="text-[11px] text-slate-500">Service Category</span>
                <p className="text-xs font-semibold text-blue-400 mt-0.5">
                  {lead.service_type || "General HVAC Diagnostic"}
                </p>
              </div>

              <div>
                <span className="text-[11px] text-slate-500">Customer Problem Description</span>
                <p className="text-xs text-slate-300 bg-slate-950/80 border border-slate-800 rounded-lg p-3 mt-1 font-mono leading-relaxed">
                  "{lead.problem_description || "No detailed description submitted."}"
                </p>
              </div>
            </div>

            {/* AI / Deterministic Qualification Evaluation Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                  Deterministic Qualification Assessment
                </h3>
                <div className="flex items-center space-x-2">
                  {qualification && (
                    <span
                      className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full ${
                        qualification.category === "HOT"
                          ? "bg-orange-950 text-orange-400 border border-orange-800"
                          : qualification.category === "WARM"
                          ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                          : qualification.category === "HUMAN_REVIEW"
                          ? "bg-amber-950 text-amber-400 border border-amber-800"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      Category: {qualification.category} (Score: {qualification.score})
                    </span>
                  )}
                  {canManage && (
                    <button
                      type="button"
                      onClick={handleRunQualification}
                      disabled={qualifying}
                      className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-[11px] font-semibold text-white disabled:opacity-50 transition-colors"
                    >
                      {qualifying ? "Evaluating..." : "Run Qualification"}
                    </button>
                  )}
                </div>
              </div>

              {qualification ? (
                <div className="space-y-3 text-xs">
                  <div>
                    <span className="text-[11px] text-slate-500">Qualification Logic & Reasoning</span>
                    <p className="text-xs text-slate-300 mt-1">
                      {qualification.reasoning}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3 pt-2">
                    <div>
                      <span className="text-[11px] text-slate-500">Recommended Action</span>
                      <p className="text-xs font-semibold text-emerald-400">
                        {qualification.recommended_action || "SCHEDULE_APPOINTMENT"}
                      </p>
                    </div>
                    <div>
                      <span className="text-[11px] text-slate-500">Human Review Required</span>
                      <p className="text-xs font-semibold text-slate-300">
                        {qualification.requires_human ? "Yes — Supervisor Review" : "No — Automated"}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500">
                  Lead has not been scored by qualification engine yet.
                </p>
              )}
            </div>
          </div>

          {/* Sidebar Controls */}
          <div className="space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider pb-2 border-b border-slate-800">
                Lead Status & Urgency
              </h3>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">
                  Lifecycle Status
                </label>
                <select
                  disabled={statusUpdating || !canManage}
                  value={lead.status}
                  onChange={(e) => handleStatusChange(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 disabled:opacity-50"
                >
                  <option value="NEW">NEW</option>
                  <option value="CONTACTED">CONTACTED</option>
                  <option value="QUALIFIED">QUALIFIED</option>
                  <option value="APPOINTMENT_OFFERED">APPOINTMENT_OFFERED</option>
                  <option value="APPOINTMENT_BOOKED">APPOINTMENT_BOOKED</option>
                  <option value="UNQUALIFIED">UNQUALIFIED</option>
                </select>
              </div>

              <div>
                <span className="block text-[11px] font-medium text-slate-400">Urgency Level</span>
                <span
                  className={`inline-block mt-1 px-2.5 py-1 rounded text-xs font-bold ${
                    lead.urgency === "EMERGENCY"
                      ? "bg-red-950 text-red-400 border border-red-800"
                      : lead.urgency === "HIGH"
                      ? "bg-orange-950 text-orange-400 border border-orange-800"
                      : "bg-blue-950 text-blue-400"
                  }`}
                >
                  {lead.urgency}
                </span>
              </div>

              <div>
                <span className="block text-[11px] font-medium text-slate-400">SMS Consent</span>
                <span className="inline-block mt-1 px-2 py-0.5 rounded text-[11px] bg-slate-800 text-slate-300 font-mono">
                  {lead.sms_consent_status}
                </span>
              </div>

              <div className="pt-3 border-t border-slate-800">
                <span className="text-[11px] text-slate-500">Created At</span>
                <p className="text-xs text-slate-400 mt-0.5">
                  {new Date(lead.created_at).toLocaleString()}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

export default function LeadDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen bg-slate-950 text-slate-400">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <LeadDetailContent />
    </Suspense>
  );
}
