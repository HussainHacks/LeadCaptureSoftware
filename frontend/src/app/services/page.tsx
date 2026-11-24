"use client";

import React, { useEffect, useState } from "react";
import {
  Wrench,
  Plus,
  Flame,
  CheckCircle2,
  Clock,
  DollarSign,
  AlertCircle,
  X,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function ServicesPage() {
  const { activeOrg } = useAuth();
  const canManageServices = ["owner", "admin"].includes(activeOrg?.role || "");
  const [services, setServices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    service_name: "",
    service_code: "",
    description: "",
    estimated_duration_minutes: 60,
    base_price: 89.0,
    is_emergency_service: false,
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchServices = async () => {
    try {
      const res = await api.services.list(false);
      setServices(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load service catalog");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchServices();
  }, []);

  const handleCreateService = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrg) return;

    setSubmitting(true);
    setError(null);
    try {
      await api.services.create({
        ...formData,
        organization_id: activeOrg.id,
      });
      setIsModalOpen(false);
      setFormData({
        service_name: "",
        service_code: "",
        description: "",
        estimated_duration_minutes: 60,
        base_price: 89.0,
        is_emergency_service: false,
      });
      fetchServices();
    } catch (err: any) {
      setError(err.message || "Failed to create service offering");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DashboardLayout>
      <Header
        title="Contractor Service Catalog"
        subtitle="Standard offerings, duration, base pricing, and emergency triage definitions"
        actionButton={
          canManageServices ? (
            <button
              onClick={() => setIsModalOpen(true)}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white font-semibold shadow transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Add Service</span>
            </button>
          ) : undefined
        }
      />

      <div className="p-6 space-y-4 max-w-5xl">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {loading ? (
            <div className="col-span-3 py-12 text-center text-xs text-slate-500">
              Loading service catalog...
            </div>
          ) : services.length === 0 ? (
            <div className="col-span-3 py-12 text-center text-xs text-slate-500">
              No services defined yet. Click "Add Service" to create one.
            </div>
          ) : (
            services.map((svc) => (
              <div
                key={svc.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3 relative overflow-hidden"
              >
                {svc.is_emergency_service && (
                  <div className="absolute top-3 right-3 flex items-center space-x-1 bg-red-950 border border-red-800 text-red-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                    <Flame className="w-3 h-3 text-red-400" />
                    <span>Emergency</span>
                  </div>
                )}

                <div>
                  <h4 className="text-sm font-bold text-white">{svc.service_name}</h4>
                  <span className="text-[11px] font-mono text-slate-500 uppercase tracking-wider">
                    {svc.service_code}
                  </span>
                </div>

                {svc.description && (
                  <p className="text-xs text-slate-400 leading-relaxed">{svc.description}</p>
                )}

                <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-xs">
                  <div className="flex items-center space-x-1 text-slate-300 font-semibold">
                    <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                    <span>${svc.base_price ? Number(svc.base_price).toFixed(2) : "0.00"}</span>
                  </div>

                  <div className="flex items-center space-x-1 text-slate-400 text-[11px]">
                    <Clock className="w-3 h-3 text-blue-400" />
                    <span>{svc.estimated_duration_minutes} min</span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Modal: Add Service */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Add Service Offering</h3>
                <button
                  onClick={() => setIsModalOpen(false)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleCreateService} className="mt-4 space-y-3">
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Service Name
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.service_name}
                    onChange={(e) => setFormData({ ...formData, service_name: e.target.value })}
                    placeholder="e.g. Capacitor Replacement"
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Service Code (Unique identifier)
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.service_code}
                    onChange={(e) => setFormData({ ...formData, service_code: e.target.value })}
                    placeholder="e.g. CAP-REPLACE"
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      Base Price ($)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      required
                      value={formData.base_price}
                      onChange={(e) =>
                        setFormData({ ...formData, base_price: parseFloat(e.target.value) })
                      }
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      Est. Duration (min)
                    </label>
                    <input
                      type="number"
                      min={15}
                      step={15}
                      required
                      value={formData.estimated_duration_minutes}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          estimated_duration_minutes: parseInt(e.target.value, 10),
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div className="flex items-center space-x-2 pt-2">
                  <input
                    type="checkbox"
                    id="is_emergency"
                    checked={formData.is_emergency_service}
                    onChange={(e) =>
                      setFormData({ ...formData, is_emergency_service: e.target.checked })
                    }
                    className="rounded bg-slate-950 border-slate-800 text-red-500 focus:ring-0"
                  />
                  <label htmlFor="is_emergency" className="text-xs text-slate-300">
                    Flag as Emergency Priority Service
                  </label>
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
                    {submitting ? "Saving..." : "Save Offering"}
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
