"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Calendar,
  Clock,
  Plus,
  Search,
  CheckCircle2,
  XCircle,
  CalendarCheck,
  User,
  X,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function AppointmentsPage() {
  const { activeOrg } = useAuth();
  const canManage = ["owner", "admin", "dispatcher"].includes(activeOrg?.role || "");
  const [appointments, setAppointments] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [services, setServices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Booking Modal State
  const [isBookModalOpen, setIsBookModalOpen] = useState(false);
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [serviceType, setServiceType] = useState("Diagnostic Service Call");
  const [startDateTime, setStartDateTime] = useState("");
  const [endDateTime, setEndDateTime] = useState("");
  const [notes, setNotes] = useState("");
  const [booking, setBooking] = useState(false);

  // Reschedule Modal State
  const [rescheduleModalId, setRescheduleModalId] = useState<string | null>(null);
  const [rescheduleStart, setRescheduleStart] = useState("");
  const [rescheduleEnd, setRescheduleEnd] = useState("");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [rescheduling, setRescheduling] = useState(false);

  // Cancel Modal State
  const [cancelModalId, setCancelModalId] = useState<string | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelling, setCancelling] = useState(false);

  const fetchData = async () => {
    try {
      const [apptsRes, leadsRes, svcsRes] = await Promise.all([
        api.appointments.list({ status: statusFilter || undefined }),
        api.leads.list({ limit: 100 }),
        api.services.list(),
      ]);
      setAppointments(apptsRes);
      setLeads(leadsRes);
      setServices(svcsRes);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load dispatch data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [statusFilter]);

  const handleBookAppointment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedLeadId || !startDateTime || !endDateTime) return;

    setBooking(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const startIso = new Date(startDateTime).toISOString();
      const endIso = new Date(endDateTime).toISOString();

      await api.appointments.create({
        lead_id: selectedLeadId,
        service_id: selectedServiceId || undefined,
        service_type: serviceType,
        appointment_start: startIso,
        appointment_end: endIso,
        appointment_status: "CONFIRMED",
        notes: notes || undefined,
      });

      setIsBookModalOpen(false);
      setSuccessMsg("Appointment successfully scheduled and capacity booked!");
      setTimeout(() => setSuccessMsg(null), 4000);
      fetchData();
    } catch (err: any) {
      setError(err.message || "Failed to schedule appointment");
    } finally {
      setBooking(false);
    }
  };

  const handleRescheduleAppointment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rescheduleModalId || !rescheduleStart || !rescheduleEnd) return;

    setRescheduling(true);
    setError(null);
    setSuccessMsg(null);
    try {
      await api.appointments.reschedule(rescheduleModalId, {
        new_start_time: new Date(rescheduleStart).toISOString(),
        new_end_time: new Date(rescheduleEnd).toISOString(),
        reason: rescheduleReason || undefined,
      });
      setRescheduleModalId(null);
      setRescheduleReason("");
      setSuccessMsg("Appointment rescheduled and capacity updated!");
      setTimeout(() => setSuccessMsg(null), 4000);
      fetchData();
    } catch (err: any) {
      setError(err.message || "Failed to reschedule appointment");
    } finally {
      setRescheduling(false);
    }
  };

  const handleCancelAppointment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cancelModalId) return;

    setCancelling(true);
    setError(null);
    try {
      await api.appointments.cancel(cancelModalId, cancelReason || undefined);
      setCancelModalId(null);
      setCancelReason("");
      setSuccessMsg("Appointment cancelled; capacity slot released.");
      setTimeout(() => setSuccessMsg(null), 4000);
      fetchData();
    } catch (err: any) {
      setError(err.message || "Failed to cancel appointment");
    } finally {
      setCancelling(false);
    }
  };

  return (
    <DashboardLayout>
      <Header
        title="Technician Dispatch & Appointment Schedule"
        subtitle="Capacity-aware scheduling with exclusion constraints and automated customer reminders"
        actionButton={
          canManage ? (
            <button
              onClick={() => {
                // Pre-fill tomorrow 9:00 AM to 10:00 AM local time
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                tomorrow.setHours(9, 0, 0, 0);
                const endTomorrow = new Date(tomorrow);
                endTomorrow.setHours(10, 0, 0, 0);

                const pad = (n: number) => (n < 10 ? `0${n}` : n);
                const formatLocal = (d: Date) =>
                  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
                    d.getHours()
                  )}:${pad(d.getMinutes())}`;

                setStartDateTime(formatLocal(tomorrow));
                setEndDateTime(formatLocal(endTomorrow));
                setIsBookModalOpen(true);
              }}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white font-semibold shadow transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Book Appointment</span>
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

        {successMsg && (
          <div className="bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs rounded-xl p-4 flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* Status Filter */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-medium text-slate-400">Filter by Appointment Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Statuses</option>
              <option value="CONFIRMED">CONFIRMED</option>
              <option value="HELD">HELD</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="CANCELLED">CANCELLED</option>
              <option value="NO_SHOW">NO_SHOW</option>
            </select>
          </div>

          <span className="text-xs text-slate-500 font-mono">
            {appointments.length} Total Bookings
          </span>
        </div>

        {/* Appointments List */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl divide-y divide-slate-800/60 overflow-hidden shadow">
          {loading ? (
            <div className="py-12 text-center text-xs text-slate-500">Loading schedule...</div>
          ) : appointments.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No appointments found for selected filter.
            </div>
          ) : (
            appointments.map((appt) => {
              const isCancelled = appt.appointment_status === "CANCELLED";
              const isConfirmed = appt.appointment_status === "CONFIRMED";

              return (
                <div key={appt.id} className="p-4 flex items-center justify-between hover:bg-slate-800/40">
                  <div className="flex items-start space-x-3">
                    <div
                      className={`p-2 rounded-lg text-white shrink-0 mt-0.5 ${
                        isConfirmed ? "bg-emerald-600" : isCancelled ? "bg-slate-700" : "bg-blue-600"
                      }`}
                    >
                      <CalendarCheck className="w-5 h-5" />
                    </div>

                    <div>
                      <div className="flex items-center space-x-2">
                        <h4 className="text-xs font-bold text-white">
                          {appt.lead ? `${appt.lead.first_name} ${appt.lead.last_name}` : "Customer"}
                        </h4>
                        <span className="text-[11px] font-mono text-slate-500">
                          {appt.lead?.phone}
                        </span>
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            isConfirmed
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : isCancelled
                              ? "bg-slate-800 text-slate-400"
                              : "bg-blue-950 text-blue-400"
                          }`}
                        >
                          {appt.appointment_status}
                        </span>
                      </div>

                      <p className="text-xs text-slate-300 font-medium mt-1">
                        {appt.service_name || appt.service_type}
                      </p>

                      <div className="flex items-center space-x-4 text-[11px] text-slate-400 mt-1">
                        <div className="flex items-center space-x-1 text-blue-400">
                          <Clock className="w-3 h-3" />
                          <span>
                            {new Date(appt.appointment_start).toLocaleString()} -{" "}
                            {new Date(appt.appointment_end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        {appt.notes && (
                          <span className="italic text-slate-500">"{appt.notes}"</span>
                        )}
                        {appt.cancellation_reason && (
                          <span className="text-red-400">Cancelled: {appt.cancellation_reason}</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    {appt.lead && (
                      <Link
                        href={`/leads/${appt.lead.id}`}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors"
                      >
                        Lead
                      </Link>
                    )}

                    {isConfirmed && canManage && (
                      <>
                        <button
                          onClick={() => {
                            const pad = (n: number) => (n < 10 ? `0${n}` : n);
                            const formatLocal = (d: Date) =>
                              `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
                                d.getHours()
                              )}:${pad(d.getMinutes())}`;
                            const s = new Date(appt.appointment_start);
                            const e = new Date(appt.appointment_end);
                            setRescheduleStart(formatLocal(s));
                            setRescheduleEnd(formatLocal(e));
                            setRescheduleReason("");
                            setRescheduleModalId(appt.id);
                          }}
                          className="px-2.5 py-1 rounded bg-blue-950/60 hover:bg-blue-900/60 border border-blue-800 text-xs text-blue-300 font-medium transition-colors"
                        >
                          Reschedule
                        </button>
                        <button
                          onClick={() => {
                            setCancelModalId(appt.id);
                            setCancelReason("");
                          }}
                          className="px-2.5 py-1 rounded bg-red-950/60 hover:bg-red-900/60 border border-red-800 text-xs text-red-300 font-medium transition-colors"
                        >
                          Cancel
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Modal: Book Appointment */}
        {isBookModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Schedule Contractor Appointment</h3>
                <button
                  onClick={() => setIsBookModalOpen(false)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleBookAppointment} className="mt-4 space-y-3.5">
                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Select Qualified Lead
                  </label>
                  <select
                    required
                    value={selectedLeadId}
                    onChange={(e) => setSelectedLeadId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="">-- Choose Customer --</option>
                    {leads
                      .filter((l) =>
                        ["QUALIFIED", "APPOINTMENT_OFFERED", "APPOINTMENT_BOOKED", "NEW", "CONTACTED"].includes(
                          l.status
                        )
                      )
                      .map((lead) => (
                        <option key={lead.id} value={lead.id}>
                          {lead.first_name} {lead.last_name} ({lead.phone}) - {lead.service_type || "Diagnostic"} [{lead.status}]
                        </option>
                      ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Service Catalog Item
                  </label>
                  <select
                    value={selectedServiceId}
                    onChange={(e) => {
                      const svcId = e.target.value;
                      setSelectedServiceId(svcId);
                      const svc = services.find((s) => s.id === svcId);
                      if (svc) setServiceType(svc.service_name);
                    }}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="">-- Select Standard Service --</option>
                    {services.map((svc) => (
                      <option key={svc.id} value={svc.id}>
                        {svc.service_name} (${svc.base_price} | {svc.estimated_duration_minutes} min)
                      </option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      Start Window (Arrival)
                    </label>
                    <input
                      type="datetime-local"
                      required
                      value={startDateTime}
                      onChange={(e) => setStartDateTime(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      End Window
                    </label>
                    <input
                      type="datetime-local"
                      required
                      value={endDateTime}
                      onChange={(e) => setEndDateTime(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Technician Dispatch Notes
                  </label>
                  <textarea
                    rows={2}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="e.g. Park on driveway; beware of friendly dog in backyard."
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                  <button
                    type="button"
                    onClick={() => setIsBookModalOpen(false)}
                    className="px-3 py-1.5 rounded bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={booking || !selectedLeadId || !startDateTime || !endDateTime}
                    className="px-4 py-1.5 rounded bg-blue-600 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {booking ? "Verifying Capacity..." : "Confirm & Book Slot"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Reschedule Appointment */}
        {rescheduleModalId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Reschedule Appointment</h3>
                <button
                  onClick={() => setRescheduleModalId(null)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleRescheduleAppointment} className="mt-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      New Start Window
                    </label>
                    <input
                      type="datetime-local"
                      required
                      value={rescheduleStart}
                      onChange={(e) => setRescheduleStart(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      New End Window
                    </label>
                    <input
                      type="datetime-local"
                      required
                      value={rescheduleEnd}
                      onChange={(e) => setRescheduleEnd(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Reschedule Reason (Optional)
                  </label>
                  <input
                    type="text"
                    value={rescheduleReason}
                    onChange={(e) => setRescheduleReason(e.target.value)}
                    placeholder="e.g. Customer requested afternoon arrival"
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                  <button
                    type="button"
                    onClick={() => setRescheduleModalId(null)}
                    className="px-3 py-1.5 rounded bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Back
                  </button>
                  <button
                    type="submit"
                    disabled={rescheduling}
                    className="px-4 py-1.5 rounded bg-blue-600 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {rescheduling ? "Updating Slot..." : "Confirm Reschedule"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Cancel Appointment */}
        {cancelModalId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Cancel Appointment</h3>
                <button
                  onClick={() => setCancelModalId(null)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleCancelAppointment} className="mt-4 space-y-3">
                <p className="text-xs text-slate-300">
                  Cancelling this appointment will release the contractor time slot in PostgreSQL and
                  trigger an outbox event.
                </p>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Cancellation Reason (Optional)
                  </label>
                  <input
                    type="text"
                    value={cancelReason}
                    onChange={(e) => setCancelReason(e.target.value)}
                    placeholder="e.g. Customer rescheduled via phone"
                    className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                  <button
                    type="button"
                    onClick={() => setCancelModalId(null)}
                    className="px-3 py-1.5 rounded bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Back
                  </button>
                  <button
                    type="submit"
                    disabled={cancelling}
                    className="px-4 py-1.5 rounded bg-red-600 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
                  >
                    {cancelling ? "Releasing Slot..." : "Confirm Cancellation"}
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
