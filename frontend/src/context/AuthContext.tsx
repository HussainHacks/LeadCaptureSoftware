"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export interface UserProfile {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
  settings?: any;
}

interface AuthContextType {
  user: UserProfile | null;
  activeOrg: OrganizationSummary | null;
  organizations: OrganizationSummary[];
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
    organization_name: string;
    organization_slug: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  switchOrganization: (orgId: string) => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [activeOrg, setActiveOrg] = useState<OrganizationSummary | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const router = useRouter();

  // Load existing session on initial mount
  useEffect(() => {
    const initAuth = async () => {
      const storedToken = localStorage.getItem("leadgen_token");
      if (!storedToken) {
        setIsLoading(false);
        return;
      }

      setToken(storedToken);
      try {
        const meRes = await api.auth.me();
        setUser(meRes.user);
        setOrganizations(meRes.organizations || []);

        const storedOrgId = localStorage.getItem("leadgen_active_org_id");
        if (storedOrgId && meRes.organizations?.some((o) => o.id === storedOrgId)) {
          const current = meRes.organizations.find((o) => o.id === storedOrgId);
          setActiveOrg(current || null);
        } else if (meRes.organizations?.length > 0) {
          setActiveOrg(meRes.organizations[0]);
          localStorage.setItem("leadgen_active_org_id", meRes.organizations[0].id);
        }
      } catch (err) {
        console.warn("Session check failed; clearing token", err);
        localStorage.removeItem("leadgen_token");
        localStorage.removeItem("leadgen_active_org_id");
        setUser(null);
        setActiveOrg(null);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
  }, []);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const res = await api.auth.login({ email, password });
      localStorage.setItem("leadgen_token", res.access_token);
      setToken(res.access_token);
      setUser(res.user);
      setOrganizations(res.organizations || []);

      if (res.organizations?.length > 0) {
        setActiveOrg(res.organizations[0]);
        localStorage.setItem("leadgen_active_org_id", res.organizations[0].id);
      }
      router.push("/dashboard");
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (data: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
    organization_name: string;
    organization_slug: string;
  }) => {
    setIsLoading(true);
    try {
      const res = await api.auth.register(data);
      localStorage.setItem("leadgen_token", res.access_token);
      setToken(res.access_token);
      setUser(res.user);
      setOrganizations(res.organizations || []);

      if (res.organizations?.length > 0) {
        setActiveOrg(res.organizations[0]);
        localStorage.setItem("leadgen_active_org_id", res.organizations[0].id);
      }
      router.push("/dashboard");
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      if (localStorage.getItem("leadgen_token")) {
        await api.auth.logout();
      }
    } catch {
      // Proceed with local cleanup even if token was already expired
    } finally {
      localStorage.removeItem("leadgen_token");
      localStorage.removeItem("leadgen_active_org_id");
      setUser(null);
      setActiveOrg(null);
      setOrganizations([]);
      setToken(null);
      router.push("/login");
    }
  };

  const switchOrganization = (orgId: string) => {
    const target = organizations.find((o) => o.id === orgId);
    if (target) {
      setActiveOrg(target);
      localStorage.setItem("leadgen_active_org_id", target.id);
      window.location.reload();
    }
  };

  const refreshUser = async () => {
    try {
      const meRes = await api.auth.me();
      setUser(meRes.user);
      setOrganizations(meRes.organizations || []);
    } catch (err) {
      console.error("Failed to refresh user profile", err);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        activeOrg,
        organizations,
        token,
        isLoading,
        login,
        register,
        logout,
        switchOrganization,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
