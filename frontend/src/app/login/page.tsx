"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Flame, LogIn, Sparkles, CheckCircle2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [seedStatus, setSeedStatus] = useState<string | null>(null);
  const [demoAvailable, setDemoAvailable] = useState(false);

  useEffect(() => {
    api.demo
      .info()
      .then(() => setDemoAvailable(true))
      .catch(() => setDemoAvailable(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err.message || "Failed to sign in. Please verify your credentials.");
    } finally {
      setLoading(false);
    }
  };

  const handleFillDemo = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword("Password123!");
    setError(null);
  };

  const handleSeedDemo = async () => {
    setLoading(true);
    setSeedStatus(null);
    try {
      const res = await api.demo.seed();
      setSeedStatus("Demo dataset successfully seeded! Ready to sign in.");
      setEmail("owner@apexair.com");
      setPassword("Password123!");
    } catch (err: any) {
      setError(`Seed error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-lg shadow-blue-500/20">
            <Flame className="w-7 h-7 text-amber-300" />
          </div>
        </div>
        <h2 className="mt-4 text-center text-2xl font-bold tracking-tight text-white">
          HVAC Lead Platform
        </h2>
        <p className="mt-1 text-center text-xs text-slate-400">
          Sign in to coordinate contractor leads, messaging, and appointments
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-slate-900 border border-slate-800 py-8 px-4 shadow-xl sm:rounded-xl sm:px-10">
          {error && (
            <div className="mb-4 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-lg p-3">
              {error}
            </div>
          )}

          {seedStatus && (
            <div className="mb-4 bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs rounded-lg p-3 flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{seedStatus}</span>
            </div>
          )}

          <form className="space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="block text-xs font-medium text-slate-300">Email Address</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@contractor.com"
                className="mt-1 block w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="mt-1 block w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex justify-center items-center space-x-2 py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50"
            >
              <LogIn className="w-4 h-4" />
              <span>{loading ? "Authenticating..." : "Sign In"}</span>
            </button>
          </form>

          {/* Quick Demo Credentials Bar (Local/Dev Only) */}
          {demoAvailable && (
            <div className="mt-6 pt-5 border-t border-slate-800">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2.5">
                1-Click Demo Accounts (Dev Only)
              </p>
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => handleFillDemo("owner@apexair.com")}
                  className="px-2 py-1.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-300 hover:border-blue-500 hover:text-blue-400 font-medium transition-colors"
                >
                  Owner
                </button>
                <button
                  type="button"
                  onClick={() => handleFillDemo("dispatcher@apexair.com")}
                  className="px-2 py-1.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-300 hover:border-blue-500 hover:text-blue-400 font-medium transition-colors"
                >
                  Dispatcher
                </button>
                <button
                  type="button"
                  onClick={() => handleFillDemo("tech@apexair.com")}
                  className="px-2 py-1.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-300 hover:border-blue-500 hover:text-blue-400 font-medium transition-colors"
                >
                  Technician
                </button>
              </div>

              <div className="mt-3 flex items-center justify-between">
                <button
                  type="button"
                  onClick={handleSeedDemo}
                  className="text-[11px] text-amber-400 hover:underline flex items-center space-x-1"
                >
                  <Sparkles className="w-3 h-3 text-amber-400" />
                  <span>Re-seed Demo Data</span>
                </button>
                <Link href="/register" className="text-[11px] text-blue-400 hover:underline">
                  Create new business
                </Link>
              </div>
            </div>
          )}

          {!demoAvailable && (
            <div className="mt-5 text-center pt-4 border-t border-slate-800">
              <Link href="/register" className="text-[11px] text-blue-400 hover:underline">
                Create new business
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
