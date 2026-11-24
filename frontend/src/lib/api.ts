/**
 * Centralized API client for Real Estate Voice AI Backend.
 * Handles JWT token storage, automatic refresh-token rotation, and typed endpoints.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface UserSession {
  userId: string;
  email: string;
  role: "customer" | "admin" | "super_owner";
  accessToken: string;
  refreshToken?: string;
  fullName?: string;
  phone?: string;
  customerId?: string;
  isVerified?: boolean;
}

export interface RegisteredCustomerItem {
  customer_id: string;
  customer_name: string;
  phone: string;
  email?: string;
  preferred_location?: string;
  preferred_config?: string;
  budget_display?: string;
  budget_min?: number;
  budget_max?: number;
  registration_date: string;
  total_conversations: number;
  last_conversation_date?: string;
  is_verified: boolean;
  status: string;
  qualification_status?: string;
  lead_priority?: string;
}

export interface RegisteredCustomersResponse {
  items: RegisteredCustomerItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface CustomerPriorityRankingItem {
  rank: number;
  customer_id: string;
  customer_name: string;
  phone: string;
  email?: string;
  total_conversations: number;
  repeat_conversations: number;
  total_duration_seconds: number;
  total_duration_formatted: string;
  avg_duration_seconds: number;
  avg_duration_formatted: string;
  last_conversation_date?: string;
  priority: string;
}

export interface CustomerPriorityRankingResponse {
  items: CustomerPriorityRankingItem[];
  total: number;
  limit: number;
  offset: number;
  time_range: string;
}

export interface SiteVisitSummary {
  id: string;
  project_name?: string;
  scheduled_start: string;
  status: string;
  notes?: string;
}

export interface CustomerDetailResponse {
  customer_id: string;
  customer_name: string;
  phone: string;
  email?: string;
  is_verified: boolean;
  registration_date: string;
  preferred_location?: string;
  interested_project?: string;
  property_type?: string;
  preferred_config?: string;
  budget_display?: string;
  budget_min?: number;
  budget_max?: number;
  lead_priority?: string;
  qualification_status?: string;
  notes?: string;
  total_conversations: number;
  total_duration_formatted: string;
  avg_duration_formatted: string;
  recent_conversation_duration_formatted?: string;
  repeat_conversations: number;
  last_conversation_date?: string;
  priority_level: string;
  current_rank?: number;
  engagement_summary?: string;
  site_visit_status?: string;
  last_site_visit_date?: string;
  next_scheduled_visit?: string;
  conversations: Array<{
    id: string;
    session_id: string;
    customer_id?: string;
    customer_name?: string;
    duration_seconds: number;
    conversation_priority: string;
    created_at: string;
  }>;
  site_visits: SiteVisitSummary[];
}

export interface DatasetColumnMeta {
  column_name: string;
  detected_type: string;
  total_values: number;
  null_count: number;
  unique_values_count: number;
  is_unique: boolean;
  is_candidate_identifier: boolean;
  example_values: string[];
  sample_distinct: string[];
}

export interface DatasetWorksheetMeta {
  sheet_name: string;
  total_rows: number;
  total_columns: number;
  columns: DatasetColumnMeta[];
  candidate_identifiers: string[];
}

export interface DatasetInspectionResponse {
  filename: string;
  file_size_bytes: number;
  primary_sheet: string;
  total_primary_rows: number;
  total_worksheets: number;
  worksheets: Record<string, DatasetWorksheetMeta>;
  relationships: any[];
  candidate_identifiers: string[];
}

export interface DatasetSummaryItem {
  id: string;
  company_id?: string;
  name: string;
  filename: string;
  file_hash: string;
  version: number;
  is_active: boolean;
  status: string;
  primary_sheet: string;
  total_rows: number;
  approved_fields?: string[];
  display_identifier?: string;
  domain_name?: string;
  created_at: string;
  activated_at?: string;
}

export interface DatasetDetailResponse extends DatasetSummaryItem {
  field_labels?: Record<string, string>;
  welcome_greeting?: string;
  metadata_registry: Record<string, any>;
}

export interface DatasetApprovalPayload {
  approved_fields: string[];
  display_identifier: string;
  field_labels?: Record<string, string>;
  domain_name?: string;
  welcome_greeting?: string;
}

export interface DatasetPreviewRecord {
  id: string;
  sheet_name: string;
  display_title: string;
  voice_summary: string;
  attributes: Record<string, any>;
}

export interface DatasetPreviewQueryResponse {
  dataset_id: string;
  dataset_name: string;
  dataset_version: number;
  total_matches: number;
  records: DatasetPreviewRecord[];
  voice_grounding: string;
}

function parseJwtPayload(token: string): any | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

export function getStoredSession(): UserSession | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem("accessToken");
  const refreshToken = localStorage.getItem("refreshToken") || "";
  const role = (localStorage.getItem("userRole") as any) || "customer";
  const userId = localStorage.getItem("userId") || localStorage.getItem("customerId");
  const email = localStorage.getItem("userEmail") || "";
  const fullName = localStorage.getItem("fullName") || undefined;
  const phone = localStorage.getItem("userPhone") || undefined;
  const customerId = localStorage.getItem("customerId") || undefined;
  const isVerified = localStorage.getItem("isVerified") === "true";

  if (!token || !userId) return null;

  // Strict Expiry Guard: If token is expired and cannot be refreshed, treat session as expired
  const payload = parseJwtPayload(token);
  if (!payload || typeof payload !== "object") {
    clearStoredSession();
    return null;
  }
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp && now >= payload.exp && !refreshToken) {
    clearStoredSession();
    return null;
  }

  return { userId, email, role, accessToken: token, refreshToken, fullName, phone, customerId, isVerified };
}

export function setStoredSession(session: UserSession): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("accessToken", session.accessToken);
  if (session.refreshToken) {
    localStorage.setItem("refreshToken", session.refreshToken);
  }
  localStorage.setItem("userRole", session.role);
  localStorage.setItem("userId", session.userId);
  localStorage.setItem("userEmail", session.email);
  if (session.fullName) localStorage.setItem("fullName", session.fullName);
  if (session.phone) localStorage.setItem("userPhone", session.phone);
  if (session.customerId) localStorage.setItem("customerId", session.customerId);
  localStorage.setItem("isVerified", String(session.isVerified ?? false));
}

export function clearStoredSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("accessToken");
  localStorage.removeItem("refreshToken");
  localStorage.removeItem("userRole");
  localStorage.removeItem("userId");
  localStorage.removeItem("userEmail");
  localStorage.removeItem("fullName");
  localStorage.removeItem("userPhone");
  localStorage.removeItem("customerId");
  localStorage.removeItem("isVerified");
}

export async function getValidAccessToken(): Promise<string | null> {
  const session = getStoredSession();
  if (!session?.accessToken) return null;

  const payload = parseJwtPayload(session.accessToken);
  if (!payload || typeof payload !== "object") {
    clearStoredSession();
    return null;
  }

  const now = Math.floor(Date.now() / 1000);

  // If token is expired or expires in < 30s
  if (payload.exp && payload.exp - now < 30) {
    if (session.refreshToken) {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        });
        if (res.ok) {
          const data = await res.json();
          const updated: UserSession = {
            ...session,
            accessToken: data.access_token,
            refreshToken: data.refresh_token || session.refreshToken,
          };
          setStoredSession(updated);
          return data.access_token;
        } else {
          clearStoredSession();
          return null;
        }
      } catch {
        return null;
      }
    } else {
      // OTP-verified customer session has no refresh token
      // When expired, user must re-authenticate with OTP
      if (now >= payload.exp) {
        clearStoredSession();
        return null;
      }
    }
  }

  return session.accessToken;
}

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onRefreshed(token: string) {
  refreshSubscribers.map((cb) => cb(token));
  refreshSubscribers = [];
}

export async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const session = getStoredSession();
  const headers = new Headers(options.headers || {});

  if (session?.accessToken) {
    headers.set("Authorization", `Bearer ${session.accessToken}`);
  }

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  });

  // Handle Token Expiration and Rotation
  if (response.status === 401 && session?.refreshToken) {
    if (!isRefreshing) {
      isRefreshing = true;
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: session.refreshToken }),
        });

        if (refreshRes.ok) {
          const data = await refreshRes.json();
          setStoredSession({
            ...session,
            accessToken: data.access_token,
            refreshToken: data.refresh_token,
          });
          isRefreshing = false;
          onRefreshed(data.access_token);
        } else {
          isRefreshing = false;
          clearStoredSession();
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
          return response;
        }
      } catch (err) {
        isRefreshing = false;
        clearStoredSession();
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
        return response;
      }
    }

    // Retry with new token
    return new Promise((resolve) => {
      refreshSubscribers.push((newToken) => {
        headers.set("Authorization", `Bearer ${newToken}`);
        resolve(fetch(`${API_BASE}${url}`, { ...options, headers }));
      });
    });
  }

  return response;
}

// ----------------------------------------------------------------------------
// Typed API Services
// ----------------------------------------------------------------------------

export const api = {
  auth: {
    async customerOnboard(data: { full_name: string; phone: string; email: string }) {
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/auth/customer-session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      } catch (err: any) {
        throw new Error(
          "Unable to connect to Real Estate Voice AI backend. Please ensure the backend server is running."
        );
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Customer onboarding failed" }));
        throw new Error(err.detail || "Customer onboarding failed");
      }
      return res.json();
    },

    async requestCustomerOtp(phone: string, channel: "email" | "sms" = "email", token?: string) {
      const session = getStoredSession();
      const authToken = token || session?.accessToken;
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (authToken) {
        headers["Authorization"] = `Bearer ${authToken}`;
      }
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/auth/customer-otp-request`, {
          method: "POST",
          headers,
          body: JSON.stringify({ phone, channel }),
        });
      } catch (err: any) {
        throw new Error(
          "Unable to connect to Real Estate Voice AI backend. Please ensure the backend server is running."
        );
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to request OTP" }));
        throw new Error(err.detail || "Failed to request OTP");
      }
      return res.json();
    },

    async verifyCustomerOtp(data: { phone: string; otp_code: string; channel?: "email" | "sms" }, token?: string) {
      const session = getStoredSession();
      const authToken = token || session?.accessToken;
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (authToken) {
        headers["Authorization"] = `Bearer ${authToken}`;
      }
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/auth/customer-otp-verify`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            phone: data.phone,
            otp_code: data.otp_code,
            channel: data.channel || "email",
          }),
        });
      } catch (err: any) {
        throw new Error(
          "Unable to connect to Real Estate Voice AI backend. Please ensure the backend server is running."
        );
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Invalid or expired OTP" }));
        throw new Error(err.detail || "Invalid or expired OTP");
      }
      return res.json();
    },

    async register(data: { email: string; password: string; role?: string; full_name?: string; phone?: string }) {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Registration failed" }));
        throw new Error(err.detail || "Registration failed");
      }
      return res.json();
    },

    async login(data: { email: string; password: string; is_admin_login?: boolean }) {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Login failed" }));
        throw new Error(err.detail || "Incorrect email or password");
      }
      return res.json();
    },

    async logout(refreshToken?: string) {
      try {
        await fetchWithAuth("/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } finally {
        clearStoredSession();
      }
    },

    async getMe() {
      const res = await fetchWithAuth("/auth/me");
      if (!res.ok) throw new Error("Failed to load user profile");
      return res.json();
    },
  },

  admin: {
    async getConversations(params?: { priority?: string; date_from?: string; date_to?: string; limit?: number; offset?: number }) {
      const q = new URLSearchParams();
      if (params?.priority) q.set("priority", params.priority);
      if (params?.date_from) q.set("date_from", params.date_from);
      if (params?.date_to) q.set("date_to", params.date_to);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));

      const res = await fetchWithAuth(`/admin/conversations?${q.toString()}`);
      if (!res.ok) throw new Error("Failed to load Conversation Priority Table");
      return res.json();
    },

    async getCustomers(params?: { search?: string; lead_priority?: string; limit?: number; offset?: number }) {
      const q = new URLSearchParams();
      if (params?.search) q.set("search", params.search);
      if (params?.lead_priority) q.set("lead_priority", params.lead_priority);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));

      const res = await fetchWithAuth(`/admin/customers?${q.toString()}`);
      if (!res.ok) throw new Error("Failed to load Total Customer Details Table");
      return res.json();
    },

    async getRegisteredCustomers(params?: { search?: string; status_filter?: string; limit?: number; offset?: number }): Promise<RegisteredCustomersResponse> {
      const q = new URLSearchParams();
      if (params?.search) q.set("search", params.search);
      if (params?.status_filter) q.set("status_filter", params.status_filter);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));

      const res = await fetchWithAuth(`/admin/customers/registered?${q.toString()}`);
      if (!res.ok) throw new Error("Failed to load All Registered Customers Table");
      return res.json();
    },

    async getPriorityRanking(params?: { search?: string; time_range?: string; priority_filter?: string; limit?: number; offset?: number }): Promise<CustomerPriorityRankingResponse> {
      const q = new URLSearchParams();
      if (params?.search) q.set("search", params.search);
      if (params?.time_range) q.set("time_range", params.time_range);
      if (params?.priority_filter) q.set("priority_filter", params.priority_filter);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));

      const res = await fetchWithAuth(`/admin/customers/priority-ranking?${q.toString()}`);
      if (!res.ok) throw new Error("Failed to load Customer Priority Ranking Table");
      return res.json();
    },

    async getCustomerDetails(customerId: string): Promise<CustomerDetailResponse> {
      const res = await fetchWithAuth(`/admin/customers/${encodeURIComponent(customerId)}/details`);
      if (!res.ok) throw new Error("Failed to load customer details");
      return res.json();
    },
  },

  customer: {
    async getProfile() {
      const res = await fetchWithAuth("/customer/profile");
      if (!res.ok) throw new Error("Failed to load profile");
      return res.json();
    },

    async getLeads() {
      const res = await fetchWithAuth("/customer/leads");
      if (!res.ok) throw new Error("Failed to load leads");
      return res.json();
    },

    async getRequirements() {
      const res = await fetchWithAuth("/customer/requirements");
      if (!res.ok) throw new Error("Failed to load requirements");
      return res.json();
    },

    async updateRequirements(data: any) {
      const res = await fetchWithAuth("/customer/requirements", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to update requirements");
      return res.json();
    },

    async getSiteVisits() {
      const res = await fetchWithAuth("/customer/site-visits");
      if (!res.ok) throw new Error("Failed to load site visits");
      return res.json();
    },
  },

  superOwner: {
    async getTranscript(sessionId: string) {
      const res = await fetchWithAuth(`/super-owner/conversations/${sessionId}/transcript`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to access transcript" }));
        throw new Error(err.detail || "Forbidden or transcript not found");
      }
      return res.json();
    },

    async getAudio(sessionId: string) {
      const res = await fetchWithAuth(`/super-owner/conversations/${sessionId}/audio`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to access audio" }));
        throw new Error(err.detail || "Forbidden or audio not found");
      }
      return res.json();
    },

    async getAuditLogs(params?: { action?: string; user_id?: string; resource_type?: string; limit?: number; offset?: number }) {
      const q = new URLSearchParams();
      if (params?.action) q.set("action", params.action);
      if (params?.user_id) q.set("user_id", params.user_id);
      if (params?.resource_type) q.set("resource_type", params.resource_type);
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));

      const res = await fetchWithAuth(`/super-owner/audit-logs?${q.toString()}`);
      if (!res.ok) throw new Error("Failed to load audit logs");
      return res.json();
    },

    async previewIngestion(file: File) {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetchWithAuth("/ingestion/preview", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Ingestion preview failed" }));
        throw new Error(err.detail || "Ingestion preview failed");
      }
      return res.json();
    },

    async executeIngestion(file: File, mappings: Record<string, string>, conflictStrategy: string = "new_version") {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("mappings_json", JSON.stringify(mappings));
      formData.append("conflict_strategy", conflictStrategy);

      const res = await fetchWithAuth("/ingestion/execute", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Ingestion execution failed" }));
        throw new Error(err.detail || "Ingestion execution failed");
      }
      return res.json();
    },

    async rollbackIngestion(batchId: string) {
      const res = await fetchWithAuth(`/ingestion/rollback/${batchId}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Rollback failed" }));
        throw new Error(err.detail || "Rollback failed");
      }
      return res.json();
    },

    async getBatches() {
      const res = await fetchWithAuth("/ingestion/batches");
      if (!res.ok) throw new Error("Failed to load ingestion batches");
      return res.json();
    },
  },

  datasets: {
    async inspect(file: File): Promise<DatasetInspectionResponse> {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetchWithAuth("/datasets/inspect", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "File inspection failed" }));
        throw new Error(err.detail || "File inspection failed");
      }
      return res.json();
    },

    async upload(file: File, datasetName?: string, companyId?: string): Promise<DatasetDetailResponse> {
      const formData = new FormData();
      formData.append("file", file);
      if (datasetName) formData.append("dataset_name", datasetName);
      if (companyId) formData.append("company_id", companyId);

      const res = await fetchWithAuth("/datasets/upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || "Upload failed");
      }
      return res.json();
    },

    async approve(datasetId: string, payload: DatasetApprovalPayload, companyId?: string): Promise<DatasetDetailResponse> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/${datasetId}/approve${q}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Approval failed" }));
        throw new Error(err.detail || "Approval failed");
      }
      return res.json();
    },

    async activate(datasetId: string, companyId?: string): Promise<DatasetSummaryItem> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/${datasetId}/activate${q}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Activation failed" }));
        throw new Error(err.detail || "Activation failed");
      }
      return res.json();
    },

    async list(companyId?: string): Promise<DatasetSummaryItem[]> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets${q}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to list datasets" }));
        throw new Error(err.detail || "Failed to list datasets");
      }
      return res.json();
    },

    async getActive(companyId?: string): Promise<DatasetDetailResponse | null> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/active${q}`);
      if (!res.ok) {
        if (res.status === 404) return null;
        const err = await res.json().catch(() => ({ detail: "Failed to get active dataset" }));
        throw new Error(err.detail || "Failed to get active dataset");
      }
      return res.json();
    },

    async getById(datasetId: string, companyId?: string): Promise<DatasetDetailResponse> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/${datasetId}${q}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to get dataset" }));
        throw new Error(err.detail || "Failed to get dataset");
      }
      return res.json();
    },

    async rollback(datasetId: string, companyId?: string): Promise<any> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/${datasetId}/rollback${q}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Rollback failed" }));
        throw new Error(err.detail || "Rollback failed");
      }
      return res.json();
    },

    async previewQuery(payload: {
      query_text?: string;
      filters?: Record<string, any>;
      dataset_id?: string;
      limit?: number;
    }, companyId?: string): Promise<DatasetPreviewQueryResponse> {
      const q = companyId ? `?company_id=${companyId}` : "";
      const res = await fetchWithAuth(`/datasets/preview-query${q}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Preview query failed" }));
        throw new Error(err.detail || "Preview query failed");
      }
      return res.json();
    },

    async listCompanies(): Promise<{ id: string; name: string; slug: string }[]> {
      const res = await fetchWithAuth("/datasets/companies");
      if (!res.ok) {
        return [];
      }
      return res.json();
    },
  },
};

export async function createLocalTestSession(): Promise<{
  session_id: string;
  token: string;
  mode: string;
  dataset_name: string;
  expires_in_seconds: number;
  driver_mode?: "MOCK" | "LIVE";
  driver_message?: string;
  model_id?: string;
  aws_region?: string;
}> {
  const res = await fetch(`${API_BASE}/voice/local-test-session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Server returned HTTP ${res.status}`);
  }
  return res.json();
}
