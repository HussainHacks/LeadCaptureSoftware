"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  MessageSquare,
  Calendar,
  Wrench,
  BarChart3,
  Settings,
  LogOut,
  Flame,
  Building2,
  ChevronDown,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export function Sidebar() {
  const pathname = usePathname();
  const { user, activeOrg, organizations, switchOrganization, logout } = useAuth();

  const navigation = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "Leads", href: "/leads", icon: Users },
    { name: "Conversations", href: "/conversations", icon: MessageSquare },
    { name: "Appointments", href: "/appointments", icon: Calendar },
    { name: "Services", href: "/services", icon: Wrench },
    { name: "Analytics", href: "/analytics", icon: BarChart3 },
    { name: "Settings", href: "/settings", icon: Settings },
  ];

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col h-screen fixed left-0 top-0 z-40 select-none">
      {/* Brand & Organization Header */}
      <div className="p-4 border-b border-slate-800">
        <div className="flex items-center space-x-2.5 mb-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
            <Flame className="w-5 h-5 text-amber-300" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-tight text-white leading-tight">LeadGen MVP</h1>
            <p className="text-[11px] text-slate-400 font-medium">HVAC Lead Platform</p>
          </div>
        </div>

        {/* Tenant Organization Switcher */}
        {activeOrg && (
          <div className="mt-2 bg-slate-950/70 border border-slate-800 rounded-lg p-2 flex items-center justify-between">
            <div className="flex items-center space-x-2 truncate w-full">
              <Building2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <div className="truncate flex-1">
                {organizations.length > 1 ? (
                  <select
                    value={activeOrg.id}
                    onChange={(e) => switchOrganization(e.target.value)}
                    className="w-full bg-transparent text-xs font-semibold text-slate-200 focus:outline-none cursor-pointer"
                  >
                    {organizations.map((org) => (
                      <option key={org.id} value={org.id} className="bg-slate-900 text-slate-200">
                        {org.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <p className="text-xs font-semibold text-slate-200 truncate">{activeOrg.name}</p>
                )}
                <p className="text-[10px] text-slate-500 uppercase tracking-wider">{activeOrg.role}</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navigation.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                isActive
                  ? "bg-blue-600/15 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? "text-blue-400" : "text-slate-400"}`} />
              <span>{item.name}</span>
            </Link>
          );
        })}
      </nav>

      {/* User info & Logout */}
      <div className="p-3 border-t border-slate-800 bg-slate-900/50">
        <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-slate-950/40">
          <div className="truncate pr-2">
            <p className="text-xs font-medium text-slate-200 truncate">
              {user ? `${user.first_name} ${user.last_name}` : "User"}
            </p>
            <p className="text-[11px] text-slate-500 truncate">{user?.email}</p>
          </div>
          <button
            onClick={logout}
            title="Log out"
            className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-950/30 rounded-md transition-colors"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
