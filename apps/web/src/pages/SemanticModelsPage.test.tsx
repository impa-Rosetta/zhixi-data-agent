import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SemanticModelsPage } from './SemanticModelsPage'

const model = {
  id: 'model-1', workspace_id: 'workspace-1', name: '制造质量标准模型', description: 'A07 标准模型', status: 'draft' as const,
  version: 1, draft_revision: 1, published_version: null, updated_at: '2026-09-07T00:00:00Z', content_digest: 'abc',
  counts: { entities: 3, attributes: 22, relationships: 1, dimensions: 4, metrics: 19, mappings: 0 },
  document: { entities: [], relationships: [], dimensions: [], mappings: [], metrics: [{ key: 'defect_rate', name: '缺陷率', description: '先汇总分子分母再相除', formula: { type: 'ratio_of_sums', attribute: null, numerator: 'inspection.defect_quantity', denominator: 'inspection.inspected_quantity', scale: 100, zero_division: 'null' as const }, unit: '%', time_grain: null, supported_dimensions: ['order'], aliases: ['不良率'] }] },
}

vi.mock('../features/auth/context', () => ({ useAuth: () => ({ workspace: { id: 'workspace-1' } }) }))
vi.mock('../features/dataSources/api', () => ({
  useDataSources: () => ({ data: { items: [{ id: 'source-1', name: 'MES PostgreSQL' }] } }),
  useCatalogSnapshots: () => ({ data: [] }),
}))
vi.mock('../features/semantic/api', async (loadOriginal) => {
  const actual = await loadOriginal<typeof import('../features/semantic/api')>()
  return {
    ...actual,
    useSemanticModels: () => ({ data: { items: [model], total: 1 }, isLoading: false }),
    useCreateManufacturingTemplate: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useCreateSemanticDraft: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useMappingCandidates: () => ({ data: undefined }),
    useSaveSemanticDraft: () => ({ isPending: false, mutateAsync: vi.fn() }),
    usePublishSemanticModel: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

describe('SemanticModelsPage', () => {
  beforeEach(() => vi.clearAllMocks())
  it('shows metric lineage and real mapping controls', () => {
    render(<QueryClientProvider client={new QueryClient()}><SemanticModelsPage /></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: '语义模型工作台' })).toBeInTheDocument()
    expect(screen.getByText('缺陷率')).toBeInTheDocument()
    expect(screen.getByText(/SUM\(inspection.defect_quantity\)/)).toBeInTheDocument()
    expect(screen.getByLabelText('数据源')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发布不可变版本' })).toBeEnabled()
  })
})
