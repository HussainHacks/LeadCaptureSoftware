"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Users,
  Search,
  Plus,
  Flame,
  MessageSquare,
  ShieldAlert,
  ArrowRight,
  Filter,
  CheckCircle2,
  X,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function LeadsPage() {
  const { activeOrg } = useAuth();
  const canManage = ["owner", "admin", "dispatcher"].includes(activeOrg?.role || "");
  const [leads, setLeads] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [urgencyFilter, setUrgencyFilter] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form for creating new lead manually
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    email: "",
    street_address: "",
    postal_code: "",
    service_type: "Air Conditioning Repair",
    equipment_type: "Central AC",
    problem_description: "",
    urgency: "MEDIUM",
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchLeads = async () => {
    try {
      const res = await api.leads.list({
        status: statusFilter || undefined,
        urgency: urgencyFilter || undefined,
        q: search || undefined,
      });
      setLeads(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load leads");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeads();
  }, [statusFilter, urgencyFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchLeads();
  };

  const handleCreateLead = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.leads.create(formData);
      setIsModalOpen(false);
      setFormData({
        first_name: "",
        last_name: "",
        phone: "",
        email: "",
        street_address: "",
        postal_code: "",
        service_type: "Air Conditioning Repair",
        equipment_type: "Central AC",
        problem_description: "",
        urgency: "MEDIUM",
      });
      fetchLeads();
    } catch (err: any) {
      setError(err.message || "Failed to create lead");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DashboardLayout>
      <Header
        title="Lead Management & Qualification"
        subtitle="Inbound HVAC customer inquiries, deterministic qualification, and conversation routing"
        actionButton={
          canManage ? (
            <button
              onClick={() => setIsModalOpen(true)}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white font-semibold shadow transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New Lead</span>
            </button>
          ) : undefined
        }
      />

      <div className="p-6 space-y-4">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {/* Filter & Search Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3">
          <form onSubmit={handleSearchSubmit} className="flex-1 min-w-[280px] relative">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search leads by name, phone, or issue..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </form>

          <div className="flex items-center space-x-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Statuses</option>
              <option value="NEW">New</option>
              <option value="CONTACTED">Contacted</option>
              <option value="QUALIFIED">Qualified</option>
              <option value="APPOINTMENT_OFFERED">Appt Offered</option>
              <option value="APPOINTMENT_BOOKED">Appt Booked</option>
              <option value="UNQUALIFIED">Unqualified</option>
            </select>

            <select
              value={urgencyFilter}
              onChange={(e) => setUrgencyFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Urgencies</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="EMERGENCY">Emergency</option>
            </select>

            {(statusFilter || urgencyFilter || search) && (
              <button
                onClick={() => {
                  setStatusFilter("");
                  setUrgencyFilter("");
                  setSearch("");
                }}
                className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Leads Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                <th className="py-3 px-4">Customer</th>
                <th className="py-3 px-4">Service & ZIP</th>
                <th className="py-3 px-4">Urgency</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Qualification</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-xs">
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500">
                    Loading inquiries...
                  </td>
                </tr>
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500">
                    No leads found matching criteria.
                  </td>
                </tr>
              ) : (
                leads.map((lead) => (
                  <tr key={lead.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-200">
                        {lead.first_name} {lead.last_name}
                      </div>
                      <div className="text-[11px] text-slate-500">{lead.phone}</div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="text-slate-300">{lead.service_type || "Diagnostic"}</div>
                      <div className="text-[11px] font-mono text-slate-500">
                        ZIP: {lead.postal_code || "Unknown"}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium ${
                          lead.urgency === "EMERGENCY"
                            ? "bg-red-950 text-red-400 border border-red-800 font-bold"
                            : lead.urgency === "HIGH"
                            ? "bg-orange-950 text-orange-400 border border-orange-800"
                            : lead.urgency === "MEDIUM"
                            ? "bg-blue-950 text-blue-400"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {lead.urgency}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-300">
                        {lead.status}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      {lead.latest_qualification ? (
                        <div className="flex items-center space-x-1.5">
                          <span
                            className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                              lead.latest_qualification.category === "HOT"
                                ? "bg-orange-950 text-orange-400 border border-orange-800"
                                : lead.latest_qualification.category === "WARM"
                                ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                                : lead.latest_qualification.category === "HUMAN_REVIEW"
                                ? "bg-amber-950 text-amber-400 border border-amber-800"
                                : "bg-slate-800 text-slate-400"
                            }`}
                          >
                            {lead.latest_qualification.category} ({lead.latest_qualification.score})
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-500 text-[11px]">Unscored</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right space-x-2">
                      <Link
                        href={`/leads/${lead.id}`}
                        className="text-xs text-blue-400 hover:text-blue-300 font-medium"
                      >
                        Profile
                      </Link>
                      {lead.active_conversation && (
                        <Link
                          href={`/conversations/${lead.active_conversation.id}`}
                          className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
                        >
                          Chat
                        </Link>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Modal: Manual Inbound Lead Creation */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Create & Qualify Inbound Lead</h3>
                <button
                  onClick={() => setIsModalOpen(false)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleCreateLead} className="mt-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">First Name</label>
                    <input
                      type="text"
                      required
                      value={formData.first_name}
                      onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">Last Name</label>
                    <input
                      type="text"
                      required
                      value={formData.last_name}
                      onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">Phone</label>
                    <input
                      type="text"
                      required
                      value={formData.phone}
                      onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                      placeholder="+15551234567"
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">ZIP Code</label>
                    <input
                      type="text"
                      required
                      value={formData.postal_code}
                      onChange={(e) => setFormData({ ...formData, postal_code: e.target.value })}
                      placeholder="e.g. 75001"
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300">Street Address</label>
                  <input
                    type="text"
                    value={formData.street_address}
                    onChange={(e) => setFormData({ ...formData, street_address: e.target.value })}
                    placeholder="123 Main St, Dallas, TX"
                    className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">Service Needed</label>
                    <select
                      value={formData.service_type}
                      onChange={(e) => setFormData({ ...formData, service_type: e.target.value })}
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    >
                      <option value="Air Conditioning Repair">AC Repair</option>
                      <option value="Emergency AC Repair">Emergency AC Repair</option>
                      <option value="Furnace Safety Inspection & Tune-Up">Heating Tune-Up</option>
                      <option value="Heat Pump Installation">Heat Pump Install</option>
                      <option value="Ductwork Sealing & Air Quality">Ductwork & Air Quality</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300">Urgency</label>
                    <select
                      value={formData.urgency}
                      onChange={(e) => setFormData({ ...formData, urgency: e.target.value })}
                      className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    >
                      <option value="LOW">Low (Next Week)</option>
                      <option value="MEDIUM">Medium (1-2 Days)</option>
                      <option value="HIGH">High (Today)</option>
                      <option value="EMERGENCY">Emergency (Immediate)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300">Problem Description</label>
                  <textarea
                    rows={3}
                    required
                    value={formData.problem_description}
                    onChange={(e) => setFormData({ ...formData, problem_description: e.target.value })}
                    placeholder="Describe HVAC symptoms, unit sounds, or error codes..."
                    className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-3 py-1.5 rounded bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="px-4 py-1.5 rounded bg-blue-600 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {submitting ? "Processing..." : "Qualify & Save Lead"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
