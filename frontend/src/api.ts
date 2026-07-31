export type CoreHealth = { status: string; core: string; schema_version: number };
export type CoreCapabilities = {
  formal_platforms: string[];
  workflow_controller: string;
  external_model_required: boolean;
  final_submission_actor: string;
  stage: number;
};

export type Evidence = {
  page: number;
  text: string;
  bbox: [number, number, number, number];
  method: "text_layer" | "ocr";
  confidence: number;
};
export type ProposedField = {
  field_key: string;
  value: unknown;
  confidence: number;
  evidence: Evidence[];
};
export type ResumeExtraction = {
  proposed_fields: ProposedField[];
  quality: {
    page_count: number;
    character_count: number;
    printable_ratio: number;
    ocr_pages: number[];
    needs_review: boolean;
    warnings: string[];
  };
};
export type ResumeResource = {
  resource_id: string;
  original_name: string;
  duplicate: boolean;
};
export type ProfileVersion = {
  id: string;
  profile_id: string;
  version_number: number;
  status: "confirmed" | "archived";
  source_file_resource_id: string;
  fields: Record<string, unknown>;
  created_at: string;
};
export type Profile = {
  id: string;
  row_version: number;
  active_version_id: string;
  active_version: ProfileVersion;
  created_at: string;
  archived_at: string | null;
};
export type ChangeProposal = {
  id: string;
  status: string;
  changes: Record<string, { old: unknown; new: unknown }>;
};
export type Application = {
  id: string;
  platform: string;
  profile_version_id: string;
  state: string;
  state_reason: string | null;
  row_version: number;
  source_url: string;
  title: string | null;
  company: string | null;
  form_values: Record<string, unknown> | null;
  updated_at: string;
};
export type BrowserTask = {
  application_id: string;
  task_id: string;
  state: string;
  message: string;
  page_url: string | null;
  filled_fields: string[];
  skipped_fields: string[];
};
export type InteractionHint = {
  id: string;
  field_key: string;
  locator_strategy: string;
  locator_value: string;
  success_count: number;
  review_status: string;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Keep HTTP fallback.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(url: string, body?: unknown) =>
  request<T>(url, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export async function loadCoreStatus() {
  const [health, capabilities] = await Promise.all([
    request<CoreHealth>("/api/v2/health"),
    request<CoreCapabilities>("/api/v2/system/capabilities"),
  ]);
  return { health, capabilities };
}

export const listProfiles = () => request<Profile[]>("/api/v2/profiles");
export const listVersions = (profileId: string) =>
  request<ProfileVersion[]>(`/api/v2/profiles/${profileId}/versions`);
export async function uploadAndExtract(file: File) {
  const form = new FormData();
  form.append("file", file);
  const resource = await request<ResumeResource>("/api/v2/resumes", {
    method: "POST",
    body: form,
  });
  const result = await post<{ resource_id: string; extraction: ResumeExtraction }>(
    `/api/v2/resume-resources/${resource.resource_id}/extract`,
  );
  return { resource, extraction: result.extraction };
}
export const createProfile = (fields: Record<string, unknown>, resourceId: string) =>
  post<ProfileVersion>("/api/v2/profiles", {
    fields,
    source_file_resource_id: resourceId,
  });
export const createProposal = (
  profile: Profile,
  resourceId: string,
  proposedFields: Record<string, unknown>,
) =>
  post<ChangeProposal>(`/api/v2/profiles/${profile.id}/change-proposals`, {
    base_version_id: profile.active_version_id,
    source_file_resource_id: resourceId,
    proposed_fields: proposedFields,
  });
export const acceptProposal = (proposalId: string, selectedFields: string[], expected: number) =>
  post<ProfileVersion>(`/api/v2/change-proposals/${proposalId}/accept`, {
    selected_fields: selectedFields,
    expected_version: expected,
  });
export const activateVersion = (profileId: string, versionId: string, expected: number) =>
  post<ProfileVersion>(`/api/v2/profiles/${profileId}/versions/${versionId}/activate`, {
    expected_version: expected,
  });
export const archiveVersion = (profileId: string, versionId: string, expected: number) =>
  post<ProfileVersion>(`/api/v2/profiles/${profileId}/versions/${versionId}/archive`, {
    expected_version: expected,
  });
export const deleteVersion = (profileId: string, versionId: string, expected: number) =>
  request<void>(
    `/api/v2/profiles/${profileId}/versions/${versionId}?expected_version=${expected}`,
    { method: "DELETE" },
  );

export const listApplications = () => request<Application[]>("/api/v2/applications");
export const createApplication = (payload: {
  source_url: string;
  profile_version_id: string;
  title?: string;
  company?: string;
}) => post<Application>("/api/v2/applications", payload);
export const prepareApplication = (
  id: string,
  formValues: Record<string, unknown>,
  expected: number,
) =>
  post<Application>(`/api/v2/applications/${id}/prepare`, {
    form_values: formValues,
    expected_version: expected,
  });
export const approveApplication = (id: string, expected: number) =>
  post<Application>(`/api/v2/applications/${id}/approve-review`, {
    expected_version: expected,
  });
export const openBrowser = (id: string) =>
  post<BrowserTask>(`/api/v2/applications/${id}/browser/open`);
export const continueBrowser = (id: string) =>
  post<BrowserTask>(`/api/v2/applications/${id}/browser/continue`);
export const observeSubmission = (id: string) =>
  post<BrowserTask>(`/api/v2/applications/${id}/browser/observe-submission`);

export const listHints = () => request<InteractionHint[]>("/api/v2/interaction-hints");
export const reviewHint = (id: string, status: "approved" | "disabled") =>
  post<InteractionHint>(`/api/v2/interaction-hints/${id}/review`, { status });
