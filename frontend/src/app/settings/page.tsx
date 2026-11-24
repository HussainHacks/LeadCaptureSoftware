"use client";

import React, { useEffect, useState } from "react";
import {
  Settings,
  Building2,
  Users,
  ShieldCheck,
  RefreshCw,
  Clock,
  MapPin,
  CheckCircle2,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const { activeOrg } = useAuth();
  const [orgDetails, setOrgDetails] = useState<any>(null);
  const [members, setMembers] = useState<any[]>([]);
  const [outboxStatus, setOutboxStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form state
  const [businessName, setBusinessName] = useState("");
  const [serviceZips, setServiceZips] = useState("");
  const [safetyPhone, setSafetyPhone] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchData = async () => {
    if (!activeOrg) return;
    try {
      const [orgRes, membersRes, outboxRes] = await Promise.all([
        api.organizations.get(activeOrg.id),
        api.organizations.members(activeOrg.id),
        api.outbox.status(),
      ]);
      setOrgDetails(orgRes);
      setMembers(membersRes);
      setOutboxStatus(outboxRes);

      setBusinessName(orgRes.name || "");
      const zips = orgRes.settings?.service_area_zips || [];
      setServiceZips(Array.isArray(zips) ? zips.join(", ") : "");
      setSafetyPhone(orgRes.settings?.safety_escalation_phone || "");
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load organization settings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeOrg]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrg) return;

    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const parsedZips = serviceZips
        .split(",")
        .map((z) => z.trim())
        .filter(Boolean);

      const updatedSettings = {
        ...(orgDetails?.settings || {}),
        service_area_zips: parsedZips,
        safety_escalation_phone: safetyPhone,
      };

      await api.organizations.update(activeOrg.id, {
        name: businessName,
        settings: updatedSettings,
      });

      setSuccessMsg("Contractor settings and service territory saved!");
      setTimeout(() => setSuccessMsg(null), 4000);
      fetchData();
    } catch (err: any) {
      setError(err.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <DashboardLayout>
      <Header
        title="Organization Settings & Safety Protocols"
        subtitle="Manage business configuration, service territory ZIP codes, and transactional outbox status"
      />

      <div className="p-6 space-y-6 max-w-4xl">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {successMsg && (
          <div className="bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs rounded-xl p-4 flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* Business Settings Form */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2 pb-3 border-b border-slate-800">
            <Building2 className="w-4 h-4 text-blue-400" />
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
              Contractor Identity & Territory
            </h3>
          </div>

          <form onSubmit={handleSaveSettings} className="space-y-4">
            <div>
              <label className="block text-[11px] font-medium text-slate-300 mb-1">
                Contractor Business Name
              </label>
              <input
                type="text"
                required
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-slate-300 mb-1">
                Service Area ZIP Codes (Comma separated)
              </label>
              <input
                type="text"
                value={serviceZips}
                onChange={(e) => setServiceZips(e.target.value)}
                placeholder="75001, 75002, 75003, 75004, 75005"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"
              />
              <p className="text-[11px] text-slate-500 mt-1">
                Leads outside these ZIP codes will be deterministically scored as UNQUALIFIED (COLD).
              </p>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-slate-300 mb-1">
                Safety Escalation Emergency Phone
              </label>
              <input
                type="text"
                value={safetyPhone}
                onChange={(e) => setSafetyPhone(e.target.value)}
                placeholder="+15559114822"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"
              />
              <p className="text-[11px] text-slate-500 mt-1">
                Internal phone notified when gas leak or CO alerts trigger automated lockout.
              </p>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end">
              {["owner", "admin"].includes(activeOrg?.role || "") ? (
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 rounded-lg bg-blue-600 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
                >
                  {saving ? "Saving..." : "Save Configuration"}
                </button>
              ) : (
                <span className="text-[11px] text-slate-500">
                  Only Owners or Admins can update organization configuration.
                </span>
              )}
            </div>
          </form>
        </div>

        {/* Transactional Outbox Queue Status */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center space-x-2">
              <RefreshCw className="w-4 h-4 text-indigo-400" />
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
                Transactional Outbox Queue Engine
              </h3>
            </div>
            <span className="text-[11px] text-slate-500 font-mono">
              Total Events: {outboxStatus?.total || 0}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { label: "Pending", key: "PENDING", color: "text-amber-400 bg-amber-950/40 border-amber-800" },
              { label: "Processing", key: "PROCESSING", color: "text-blue-400 bg-blue-950/40 border-blue-800" },
              { label: "Delivered", key: "DELIVERED", color: "text-emerald-400 bg-emerald-950/40 border-emerald-800" },
              { label: "Failed", key: "FAILED", color: "text-orange-400 bg-orange-950/40 border-orange-800" },
              { label: "Dead Letter", key: "DEAD_LETTER", color: "text-red-400 bg-red-950/40 border-red-800" },
            ].map((st) => (
              <div key={st.key} className={`border rounded-lg p-3 text-center ${st.color}`}>
                <span className="text-[10px] font-semibold uppercase">{st.label}</span>
                <p className="text-xl font-bold mt-1">{outboxStatus?.status_counts?.[st.key] || 0}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Team Members */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2 pb-3 border-b border-slate-800">
            <Users className="w-4 h-4 text-emerald-400" />
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
              Organization Team Members
            </h3>
          </div>

          <div className="divide-y divide-slate-800/60">
            {members.map((mem) => (
              <div key={mem.membership_id} className="py-2.5 flex items-center justify-between text-xs">
                <div>
                  <span className="font-semibold text-white">{mem.email}</span>
                  <span className="text-[11px] text-slate-500 ml-2 font-mono">ID: {mem.user_id.slice(0, 8)}...</span>
                </div>
                <span className="px-2 py-0.5 rounded uppercase font-semibold text-[10px] bg-slate-800 text-slate-300">
                  {mem.role}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
