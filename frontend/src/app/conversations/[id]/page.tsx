"use client";

import React, { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  MessageSquare,
  ShieldAlert,
  Bot,
  User,
  Send,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Flame,
  Sparkles,
  Lock,
  Unlock,
  X,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

function ConversationThreadContent() {
  const params = useParams();
  const router = useRouter();
  const { activeOrg } = useAuth();
  const conversationId = params?.id as string;
  const canManage = ["owner", "admin", "dispatcher"].includes(activeOrg?.role || "");

  const [conversation, setConversation] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Manual outbound message state
  const [outboundText, setOutboundText] = useState("");
  const [sendingOutbound, setSendingOutbound] = useState(false);

  // Inbound simulation state
  const [simulateText, setSimulateText] = useState("");
  const [simulating, setSimulating] = useState(false);
  const [simulationResult, setSimulationResult] = useState<string | null>(null);

  // Safety resolve modal state
  const [isResolveModalOpen, setIsResolveModalOpen] = useState(false);
  const [resolveNotes, setResolveNotes] = useState("");
  const [resolving, setResolving] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchConversation = async () => {
    try {
      const res = await api.conversations.get(conversationId);
      setConversation(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load conversation thread");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (conversationId) fetchConversation();
  }, [conversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation?.messages]);

  // Send manual outbound staff message
  const handleSendOutbound = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!outboundText.trim()) return;

    setSendingOutbound(true);
    setError(null);
    try {
      await api.conversations.sendMessage(conversationId, outboundText.trim(), "staff");
      setOutboundText("");
      fetchConversation();
    } catch (err: any) {
      setError(err.message || "Failed to send outbound message");
    } finally {
      setSendingOutbound(false);
    }
  };

  // Simulate incoming customer reply
  const handleSimulateInbound = async (content: string) => {
    setSimulating(true);
    setError(null);
    setSimulationResult(null);
    try {
      const res = await api.conversations.simulateInbound(conversationId, content);
      if (res.safety_escalation_triggered) {
        setSimulationResult("CRITICAL SAFETY HAZARD TRIGGERED: Automated replies locked.");
      } else if (res.ai_reply_generated) {
        setSimulationResult("Simulated customer message received & automated AI reply generated!");
      } else {
        setSimulationResult("Inbound message received.");
      }
      setSimulateText("");
      fetchConversation();
      setTimeout(() => setSimulationResult(null), 6000);
    } catch (err: any) {
      setError(err.message || "Failed to simulate inbound message");
    } finally {
      setSimulating(false);
    }
  };

  // Resolve safety escalation
  const handleResolveSafety = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resolveNotes.trim()) return;

    setResolving(true);
    setError(null);
    try {
      await api.conversations.resolveSafety(conversationId, resolveNotes.trim());
      setIsResolveModalOpen(false);
      setResolveNotes("");
      fetchConversation();
    } catch (err: any) {
      setError(err.message || "Failed to resolve safety escalation");
    } finally {
      setResolving(false);
    }
  };

  // Transition status
  const handleStatusChange = async (newStatus: string) => {
    try {
      await api.conversations.changeStatus(conversationId, newStatus);
      fetchConversation();
    } catch (err: any) {
      setError(err.message || "Failed to change thread status");
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-xs text-slate-500">Loading conversation thread...</div>
      </DashboardLayout>
    );
  }

  if (!conversation) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-xs text-red-400">{error || "Conversation not found"}</div>
      </DashboardLayout>
    );
  }

  const isLocked = conversation.is_automated_reply_locked;
  const isSafety = conversation.status === "ESCALATED_SAFETY" || isLocked;

  return (
    <DashboardLayout>
      <Header
        title={
          conversation.lead
            ? `${conversation.lead.first_name} ${conversation.lead.last_name} (${conversation.lead.phone})`
            : "Conversation Thread"
        }
        subtitle={`Channel: ${conversation.channel} | Urgency: ${conversation.lead?.urgency || "MEDIUM"}`}
        actionButton={
          <div className="flex items-center space-x-2">
            <Link
              href="/conversations"
              className="flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Inbox</span>
            </Link>
            {conversation.lead && (
              <Link
                href={`/leads/${conversation.lead.id}`}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium"
              >
                Lead Profile
              </Link>
            )}
          </div>
        }
      />

      <div className="p-6 space-y-4 max-w-5xl">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-3">
            {error}
          </div>
        )}

        {simulationResult && (
          <div className="bg-blue-950/60 border border-blue-800 text-blue-300 text-xs rounded-xl p-3 flex items-center space-x-2">
            <Sparkles className="w-4 h-4 text-blue-400 shrink-0" />
            <span>{simulationResult}</span>
          </div>
        )}

        {/* 1. Critical Safety Escalation Banner */}
        {isSafety && (
          <div className="bg-red-950/90 border-2 border-red-600 rounded-xl p-4 shadow-xl">
            <div className="flex items-start justify-between">
              <div className="flex items-start space-x-3">
                <div className="p-2 bg-red-600 rounded-lg text-white shrink-0 animate-pulse">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-xs font-bold text-red-200 uppercase tracking-wider">
                    CRITICAL SAFETY HAZARD DETECTED — AUTOMATED REPLIES LOCKED
                  </h3>
                  <p className="text-xs text-red-300 mt-1">
                    An immediate hazard (suspected gas leak / carbon monoxide / electrical fire) was
                    identified in customer message history. The customer has been instructed to
                    evacuate and contact emergency services. Automated AI messaging is locked out.
                  </p>
                  <p className="text-[11px] text-red-400 font-mono mt-1">
                    Reason: {conversation.escalation_reason || "SAFETY_HAZARD"}
                  </p>
                </div>
              </div>

              {canManage && (
                <button
                  onClick={() => setIsResolveModalOpen(true)}
                  className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-bold text-white shadow transition-colors flex items-center space-x-1 shrink-0 ml-4"
                >
                  <Unlock className="w-3.5 h-3.5" />
                  <span>Resolve & Unlock</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Thread Controls Header */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center justify-between text-xs">
          <div className="flex items-center space-x-3">
            <span className="text-slate-400">Thread Status:</span>
            <select
              disabled={!canManage}
              value={conversation.status}
              onChange={(e) => handleStatusChange(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
            >
              <option value="AI_ACTIVE">AI_ACTIVE</option>
              <option value="AWAITING_CUSTOMER">AWAITING_CUSTOMER</option>
              <option value="HUMAN_TAKEOVER">HUMAN_TAKEOVER</option>
              <option value="ESCALATED_SAFETY">ESCALATED_SAFETY</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="CLOSED">CLOSED</option>
            </select>
          </div>

          <div className="flex items-center space-x-3">
            <span className="text-slate-400">Automated Reply Lock:</span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                isLocked
                  ? "bg-red-950 text-red-400 border border-red-800"
                  : "bg-emerald-950 text-emerald-400 border border-emerald-800"
              }`}
            >
              {isLocked ? "LOCKED (AI Halted)" : "UNLOCKED (AI Permitted)"}
            </span>
          </div>
        </div>

        {/* Chat Timeline Container */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[460px] overflow-hidden shadow">
          {/* Messages list */}
          <div className="flex-1 p-4 overflow-y-auto space-y-3">
            {conversation.messages && conversation.messages.length > 0 ? (
              conversation.messages.map((msg: any) => {
                const senderUpper = (msg.sender || "").toUpperCase();
                const isCustomer = senderUpper === "CUSTOMER";
                const isAi = senderUpper === "AI_AGENT";
                const isSystem = senderUpper === "SYSTEM";

                if (isSystem) {
                  return (
                    <div key={msg.id} className="my-2 flex justify-center">
                      <div className="bg-red-950/70 border border-red-700/80 rounded-lg p-3 max-w-lg text-center">
                        <div className="flex items-center justify-center space-x-1.5 text-red-400 text-xs font-bold mb-1">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>SYSTEM SAFETY ADVISORY (SIMULATED)</span>
                        </div>
                        <p className="text-xs text-red-200">{msg.message_content}</p>
                        {msg.delivery_status && (
                          <p className="text-[10px] text-red-400/80 mt-1 font-mono">
                            Status: {msg.delivery_status}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                }

                return (
                  <div
                    key={msg.id}
                    className={`flex items-start space-x-2 ${
                      isCustomer ? "justify-start" : "justify-end"
                    }`}
                  >
                    {isCustomer && (
                      <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center text-slate-300 text-xs font-semibold shrink-0">
                        <User className="w-3.5 h-3.5" />
                      </div>
                    )}

                    <div
                      className={`max-w-md rounded-xl p-3 shadow-sm ${
                        isCustomer
                          ? "bg-slate-800 text-slate-100 rounded-tl-none border border-slate-700"
                          : isAi
                          ? "bg-indigo-600 text-white rounded-tr-none shadow-indigo-600/20"
                          : "bg-blue-600 text-white rounded-tr-none shadow-blue-600/20"
                      }`}
                    >
                      <div className="flex items-center justify-between space-x-3 text-[10px] opacity-75 mb-1">
                        <span className="font-semibold uppercase tracking-wider">
                          {isCustomer ? "Customer (Simulated SMS)" : isAi ? "Simulated AI" : "Staff"}
                        </span>
                        <span>
                          {msg.delivery_status ? `${msg.delivery_status} · ` : ""}
                          {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <p className="text-xs leading-relaxed whitespace-pre-wrap">{msg.message_content}</p>
                    </div>

                    {!isCustomer && (
                      <div
                        className={`w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-semibold shrink-0 ${
                          isAi ? "bg-indigo-600" : "bg-blue-600"
                        }`}
                      >
                        {isAi ? <Bot className="w-3.5 h-3.5" /> : <User className="w-3.5 h-3.5" />}
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-slate-500">
                No messages recorded in this conversation yet.
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Outbound Staff Message Input */}
          {canManage ? (
            <form
              onSubmit={handleSendOutbound}
              className="p-3 bg-slate-950/80 border-t border-slate-800 flex items-center space-x-2"
            >
              <input
                type="text"
                value={outboundText}
                onChange={(e) => setOutboundText(e.target.value)}
                placeholder={
                  isLocked
                    ? "Manual staff reply (simulated SMS, human override)..."
                    : "Type simulated outbound staff reply..."
                }
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
              <button
                type="submit"
                disabled={sendingOutbound || !outboundText.trim()}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow disabled:opacity-50 transition-colors flex items-center space-x-1"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Send (Simulated)</span>
              </button>
            </form>
          ) : (
            <div className="p-3 bg-slate-950/80 border-t border-slate-800 text-center text-[11px] text-slate-500">
              Read-only view ({activeOrg?.role || "viewer"} role cannot send customer messages)
            </div>
          )}
        </div>

        {/* 2. Interactive "Simulate Customer Reply" Bar */}
        {canManage && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-amber-400" />
              <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                Simulation Sandbox — Inbound Customer Testing (Local Only, No Real SMS)
              </h4>
            </div>
            <p className="text-[11px] text-slate-400">
              Simulate incoming customer SMS messages to verify deterministic qualification, simulated AI
              auto-replies, HELP/STOP consent handling, and safety lockout policy:
            </p>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={simulating}
                onClick={() =>
                  handleSimulateInbound("My AC unit stopped blowing cold air and indoor temperature is 82 degrees.")
                }
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-blue-500 text-[11px] text-slate-300 font-medium transition-colors"
              >
                ❄️ Normal AC Outage
              </button>

              <button
                type="button"
                disabled={simulating}
                onClick={() =>
                  handleSimulateInbound("How much does a routine pre-summer AC tune-up cost?")
                }
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-blue-500 text-[11px] text-slate-300 font-medium transition-colors"
              >
                💰 Price / Quote Inquiry
              </button>

              <button
                type="button"
                disabled={simulating}
                onClick={() => handleSimulateInbound("HELP")}
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-cyan-500 text-[11px] text-cyan-400 font-medium transition-colors"
              >
                ℹ️ HELP
              </button>

              <button
                type="button"
                disabled={simulating}
                onClick={() => handleSimulateInbound("STOP")}
                className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-amber-500 text-[11px] text-amber-400 font-medium transition-colors"
              >
                🛑 Opt-Out (STOP)
              </button>

              <button
                type="button"
                disabled={simulating}
                onClick={() =>
                  handleSimulateInbound(
                    "I smell a strong gas odor near the heating unit and the carbon monoxide alarm is beeping!"
                  )
                }
                className="px-2.5 py-1.5 rounded-lg bg-red-950/70 border border-red-800 hover:bg-red-900/60 text-[11px] text-red-300 font-bold transition-colors"
              >
                ⚠️ Gas Leak Emergency Hazard
              </button>
            </div>

            <div className="flex items-center space-x-2 pt-2">
              <input
                type="text"
                value={simulateText}
                onChange={(e) => setSimulateText(e.target.value)}
                placeholder="Or type custom customer message to simulate..."
                className="flex-1 bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-500"
              />
              <button
                type="button"
                disabled={simulating || !simulateText.trim()}
                onClick={() => handleSimulateInbound(simulateText.trim())}
                className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-xs font-semibold text-white disabled:opacity-50 transition-colors"
              >
                {simulating ? "Simulating..." : "Simulate Inbound"}
              </button>
            </div>
          </div>
        )}

        {/* Modal: Resolve Safety Escalation */}
        {isResolveModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center space-x-2 text-red-400">
                  <ShieldAlert className="w-5 h-5" />
                  <h3 className="text-sm font-semibold text-white">Resolve Safety Escalation</h3>
                </div>
                <button
                  onClick={() => setIsResolveModalOpen(false)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleResolveSafety} className="mt-4 space-y-4">
                <p className="text-xs text-slate-300 leading-relaxed">
                  To clear emergency lockout and return this conversation to human or automated
                  dispatch, you must record an explanatory note verifying safety clearance (e.g. utility
                  shutoff confirmed or false alarm).
                </p>

                <div>
                  <label className="block text-[11px] font-medium text-slate-300 mb-1">
                    Supervisor Resolution Explanation (Required)
                  </label>
                  <textarea
                    rows={3}
                    required
                    value={resolveNotes}
                    onChange={(e) => setResolveNotes(e.target.value)}
                    placeholder="e.g., Gas company inspected premises and issued all-clear tag; safe to proceed with diagnosis."
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end space-x-2">
                  <button
                    type="button"
                    onClick={() => setIsResolveModalOpen(false)}
                    className="px-3 py-1.5 rounded bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={resolving || !resolveNotes.trim()}
                    className="px-4 py-1.5 rounded bg-red-600 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
                  >
                    {resolving ? "Unlocking..." : "Confirm Safety Clearance"}
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

export default function ConversationThreadPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen bg-slate-950 text-slate-400">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <ConversationThreadContent />
    </Suspense>
  );
}
