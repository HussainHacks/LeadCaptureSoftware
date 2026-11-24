"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  MessageSquare,
  Search,
  ShieldAlert,
  Bot,
  User,
  Clock,
  ArrowRight,
  Flame,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fetchConversations = async () => {
    try {
      const res = await api.conversations.list({
        status: statusFilter || undefined,
      });
      setConversations(res);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load conversations");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConversations();
  }, [statusFilter]);

  return (
    <DashboardLayout>
      <Header
        title="Customer Conversations & Dispatch Inbox"
        subtitle="Two-way simulated SMS communications, automated AI triage, and emergency lockout control"
      />

      <div className="p-6 space-y-4">
        {error && (
          <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl p-4">
            {error}
          </div>
        )}

        {/* Filter Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-medium text-slate-400">Filter by Thread Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Statuses</option>
              <option value="AI_ACTIVE">AI Active</option>
              <option value="AWAITING_CUSTOMER">Awaiting Customer</option>
              <option value="HUMAN_TAKEOVER">Human Takeover</option>
              <option value="ESCALATED_SAFETY">Safety Escalated (Locked)</option>
              <option value="COMPLETED">Completed</option>
              <option value="CLOSED">Closed</option>
            </select>
          </div>

          <span className="text-xs text-slate-500 font-mono">
            {conversations.length} Active Threads
          </span>
        </div>

        {/* Thread List */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl divide-y divide-slate-800/60 overflow-hidden shadow">
          {loading ? (
            <div className="py-12 text-center text-xs text-slate-500">
              Loading conversation threads...
            </div>
          ) : conversations.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No conversations found.
            </div>
          ) : (
            conversations.map((conv) => {
              const isLocked = conv.is_automated_reply_locked;
              const isSafety = conv.status === "ESCALATED_SAFETY" || isLocked;

              return (
                <Link
                  key={conv.id}
                  href={`/conversations/${conv.id}`}
                  className={`p-4 block transition-colors hover:bg-slate-800/50 ${
                    isSafety ? "bg-red-950/20 border-l-4 border-l-red-500" : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      <div
                        className={`w-9 h-9 rounded-full flex items-center justify-center text-white ${
                          isSafety
                            ? "bg-red-600 shadow-md shadow-red-600/30"
                            : conv.status === "AI_ACTIVE"
                            ? "bg-indigo-600"
                            : "bg-blue-600"
                        }`}
                      >
                        {isSafety ? (
                          <ShieldAlert className="w-4 h-4 text-white" />
                        ) : conv.status === "AI_ACTIVE" ? (
                          <Bot className="w-4 h-4 text-white" />
                        ) : (
                          <User className="w-4 h-4 text-white" />
                        )}
                      </div>

                      <div>
                        <div className="flex items-center space-x-2">
                          <h4 className="text-xs font-bold text-white">
                            {conv.lead
                              ? `${conv.lead.first_name} ${conv.lead.last_name}`
                              : "Unknown Customer"}
                          </h4>
                          <span className="text-[11px] font-mono text-slate-500">
                            {conv.lead?.phone}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-mono">
                            {conv.channel}
                          </span>
                        </div>

                        <p className="text-xs text-slate-300 mt-1 truncate max-w-xl">
                          {conv.last_message ? (
                            <span>
                              <strong className="text-slate-400 capitalize">
                                {conv.last_message.sender}:
                              </strong>{" "}
                              {conv.last_message.message_content}
                            </span>
                          ) : (
                            <span className="text-slate-500 italic">No messages yet</span>
                          )}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center space-x-3 text-right">
                      <div>
                        <span
                          className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            isSafety
                              ? "bg-red-950 border border-red-700 text-red-300"
                              : conv.status === "AI_ACTIVE"
                              ? "bg-indigo-950 border border-indigo-800 text-indigo-300"
                              : conv.status === "HUMAN_TAKEOVER"
                              ? "bg-amber-950 border border-amber-800 text-amber-300"
                              : "bg-slate-800 text-slate-300"
                          }`}
                        >
                          {conv.status}
                        </span>
                        {conv.last_message_at && (
                          <div className="text-[10px] text-slate-500 mt-1 flex items-center justify-end space-x-1">
                            <Clock className="w-2.5 h-2.5" />
                            <span>{new Date(conv.last_message_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                        )}
                      </div>

                      <ArrowRight className="w-4 h-4 text-slate-600" />
                    </div>
                  </div>
                </Link>
              );
            })
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
