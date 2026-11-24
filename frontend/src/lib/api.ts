/**
 * Centralized API client for communicating with FastAPI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export interface ApiResponse<T = any> {
  data?: T;
  error?: string;
  status: number;
}

class ApiClient {
  private getHeaders(): HeadersInit {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (typeof window !== "undefined") {
      const token = localStorage.getItem("leadgen_token");
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const orgId = localStorage.getItem("leadgen_active_org_id");
      if (orgId) {
        headers["X-Organization-ID"] = orgId;
      }
    }

    return headers;
  }

  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${API_BASE}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const headers = {
      ...this.getHeaders(),
      ...(options.headers || {}),
    };

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status} ${response.statusText}`;
      try {
        const errorJson = await response.json();
        errorMessage = errorJson.detail || errorJson.message || errorMessage;
      } catch {
        // Fall back to status text
      }
      throw new Error(errorMessage);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  // Auth endpoints
  auth = {
    login: (credentials: { email: string; password: string }) =>
      this.request<{
        access_token: string;
        token_type: string;
        user: any;
        organizations: any[];
      }>("/auth/login", {
        method: "POST",
        body: JSON.stringify(credentials),
      }),

    register: (data: {
      email: string;
      password: string;
      first_name: string;
      last_name: string;
      organization_name: string;
      organization_slug: string;
    }) =>
      this.request<{
        access_token: string;
        token_type: string;
        user: any;
        active_organization_id: string;
        organizations: any[];
      }>("/auth/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    logout: () =>
      this.request<{ message: string }>("/auth/logout", {
        method: "POST",
      }),

    me: () =>
      this.request<{
        user: any;
        active_organization: any;
        role: string | null;
        organizations: any[];
      }>("/auth/me"),
  };

  // Organizations endpoints
  organizations = {
    list: () => this.request<any[]>("/organizations"),
    get: (id: string) => this.request<any>(`/organizations/${id}`),
    update: (id: string, data: any) =>
      this.request<any>(`/organizations/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    members: (id: string) => this.request<any[]>(`/organizations/${id}/members`),
  };

  // Dashboard & Analytics
  dashboard = {
    get: () => this.request<any>("/dashboard"),
  };

  analytics = {
    get: () => this.request<any>("/analytics"),
  };

  // Leads
  leads = {
    list: (params?: { status?: string; urgency?: string; q?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.append("status", params.status);
      if (params?.urgency) q.append("urgency", params.urgency);
      if (params?.q) q.append("q", params.q);
      if (params?.limit) q.append("limit", params.limit.toString());
      const queryStr = q.toString() ? `?${q.toString()}` : "";
      return this.request<any[]>(`/leads${queryStr}`);
    },
    get: (id: string) => this.request<any>(`/leads/${id}`),
    create: (data: any) =>
      this.request<any>("/leads", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateStatus: (id: string, status: string) =>
      this.request<any>(`/leads/${id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      }),
    qualify: (id: string) =>
      this.request<any>(`/leads/${id}/qualify`, {
        method: "POST",
      }),
  };

  // Conversations & Messaging
  conversations = {
    list: (params?: { status?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.append("status", params.status);
      if (params?.limit) q.append("limit", params.limit.toString());
      const queryStr = q.toString() ? `?${q.toString()}` : "";
      return this.request<any[]>(`/conversations${queryStr}`);
    },
    get: (id: string) => this.request<any>(`/conversations/${id}`),
    sendMessage: (id: string, content: string, sender: "staff" | "ai_agent" = "staff") =>
      this.request<any>(`/conversations/${id}/messages`, {
        method: "POST",
        body: JSON.stringify({ message_content: content, sender }),
      }),
    simulateInbound: (id: string, content: string) =>
      this.request<any>(`/conversations/${id}/simulate-inbound`, {
        method: "POST",
        body: JSON.stringify({ message_content: content }),
      }),
    assign: (id: string, userId: string) =>
      this.request<any>(`/conversations/${id}/assign`, {
        method: "POST",
        body: JSON.stringify({ user_id: userId }),
      }),
    changeStatus: (id: string, status: string) =>
      this.request<any>(`/conversations/${id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      }),
    escalate: (id: string, reason: string) =>
      this.request<any>(`/conversations/${id}/escalate`, {
        method: "POST",
        body: JSON.stringify({ escalation_reason: reason, lock_automated_reply: true }),
      }),
    resolveSafety: (id: string, notes: string) =>
      this.request<any>(`/conversations/${id}/resolve-safety`, {
        method: "POST",
        body: JSON.stringify({ resolution_notes: notes }),
      }),
  };

  // Appointments
  appointments = {
    list: (params?: { status?: string; leadId?: string }) => {
      const q = new URLSearchParams();
      if (params?.status) q.append("status", params.status);
      if (params?.leadId) q.append("lead_id", params.leadId);
      const queryStr = q.toString() ? `?${q.toString()}` : "";
      return this.request<any[]>(`/appointments${queryStr}`);
    },
    get: (id: string) => this.request<any>(`/appointments/${id}`),
    create: (data: any) =>
      this.request<any>("/appointments", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    reschedule: (id: string, data: { new_start_time: string; new_end_time: string; reason?: string }) =>
      this.request<any>(`/appointments/${id}/reschedule`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    cancel: (id: string, reason?: string) =>
      this.request<any>(`/appointments/${id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ cancellation_reason: reason }),
      }),
  };

  // Services Catalog
  services = {
    list: (activeOnly: boolean = false) =>
      this.request<any[]>(`/services?active_only=${activeOnly}`),
    get: (id: string) => this.request<any>(`/services/${id}`),
    create: (data: any) =>
      this.request<any>("/services", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  };

  // Outbox
  outbox = {
    status: () => this.request<any>("/outbox/status"),
    events: (limit: number = 20) => this.request<any[]>(`/outbox/events?limit=${limit}`),
    sweep: () =>
      this.request<any>("/outbox/sweep", {
        method: "POST",
      }),
  };

  // Demo
  demo = {
    info: () => this.request<any>("/demo/info"),
    seed: () =>
      this.request<any>("/demo/seed", {
        method: "POST",
      }),
  };
}

export const api = new ApiClient();
