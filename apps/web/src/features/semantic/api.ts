import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../lib/api/client'

export type Formula = { type: string; attribute: string | null; numerator: string | null; denominator: string | null; scale: number; zero_division: 'null' }
export type SemanticAttribute = { key: string; name: string; data_type: string; is_identifier: boolean; nullable: boolean }
export type SemanticEntity = { key: string; name: string; description: string | null; attributes: SemanticAttribute[] }
export type SemanticMetric = { key: string; name: string; description: string; formula: Formula; unit: string; time_grain: string | null; supported_dimensions: string[]; aliases: string[] }
export type SemanticMapping = { semantic_attribute: string; snapshot_id: string; relation_id: string; column_id: string; confirmed: boolean; confidence: number; reason: string }
export type SemanticDocument = { entities: SemanticEntity[]; relationships: unknown[]; dimensions: { key: string; name: string }[]; metrics: SemanticMetric[]; mappings: SemanticMapping[] }
export type SemanticModel = { id: string; workspace_id: string; name: string; description: string | null; status: 'draft' | 'published' | 'archived'; version: number; draft_revision: number; published_version: number | null; counts: Record<string, number>; document: SemanticDocument; content_digest: string; updated_at: string }
export type MappingCandidate = { semantic_attribute: string; snapshot_id: string; relation_id: string; column_id: string; schema_name: string; relation_name: string; column_name: string; confidence: number; reason: string }

const keys = {
  all: (workspaceId: string) => ['workspaces', workspaceId, 'semantic-models'] as const,
  candidates: (workspaceId: string, modelId: string, snapshotId: string) => ['workspaces', workspaceId, 'semantic-models', modelId, 'candidates', snapshotId] as const,
}

export function useSemanticModels(workspaceId: string | undefined) {
  return useQuery({
    queryKey: workspaceId ? keys.all(workspaceId) : ['semantic-models', 'disabled'],
    queryFn: () => apiClient.request<{ items: SemanticModel[]; total: number }>(`/api/v1/workspaces/${workspaceId}/semantic-models`),
    enabled: Boolean(workspaceId),
  })
}

export function useCreateManufacturingTemplate(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiClient.request<SemanticModel>(`/api/v1/workspaces/${workspaceId}/semantic-models/manufacturing-template`, { method: 'POST', body: JSON.stringify({ name, description: 'A07 制造质量分析标准语义模型' }) }),
    onSuccess: async () => { if (workspaceId) await queryClient.invalidateQueries({ queryKey: keys.all(workspaceId) }) },
  })
}

export function useMappingCandidates(workspaceId: string | undefined, modelId: string | undefined, snapshotId: string | undefined) {
  return useQuery({
    queryKey: workspaceId && modelId && snapshotId ? keys.candidates(workspaceId, modelId, snapshotId) : ['mapping-candidates', 'disabled'],
    queryFn: () => apiClient.request<{ candidates: MappingCandidate[]; unmapped_attributes: string[] }>(`/api/v1/workspaces/${workspaceId}/semantic-models/${modelId}/mapping-candidates?snapshot_id=${snapshotId}`),
    enabled: Boolean(workspaceId && modelId && snapshotId),
  })
}

export function useSaveSemanticDraft(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (model: SemanticModel) => apiClient.request<SemanticModel>(`/api/v1/workspaces/${workspaceId}/semantic-models/${model.id}/draft`, { method: 'PUT', body: JSON.stringify({ version: model.version, ...model.document }) }),
    onSuccess: async () => { if (workspaceId) await queryClient.invalidateQueries({ queryKey: keys.all(workspaceId) }) },
  })
}

export function usePublishSemanticModel(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (model: SemanticModel) => apiClient.request<SemanticModel>(`/api/v1/workspaces/${workspaceId}/semantic-models/${model.id}/publish`, { method: 'POST', body: JSON.stringify({ version: model.version }) }),
    onSuccess: async () => { if (workspaceId) await queryClient.invalidateQueries({ queryKey: keys.all(workspaceId) }) },
  })
}

export function useCreateSemanticDraft(workspaceId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (model: SemanticModel) => apiClient.request<SemanticModel>(`/api/v1/workspaces/${workspaceId}/semantic-models/${model.id}/new-draft`, { method: 'POST', body: JSON.stringify({ version: model.version }) }),
    onSuccess: async () => { if (workspaceId) await queryClient.invalidateQueries({ queryKey: keys.all(workspaceId) }) },
  })
}