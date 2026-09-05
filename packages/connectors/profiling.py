from dataclasses import dataclass


@dataclass(frozen=True)
class SamplingBudget:
    max_rows_per_table: int = 20
    max_values_per_column: int = 20
    max_value_chars: int = 256
    max_bytes_per_table: int = 65_536
    max_bytes_per_job: int = 1_048_576

    def __post_init__(self) -> None:
        if not 1 <= self.max_rows_per_table <= 20:
            raise ValueError("max_rows_per_table must be between 1 and 20")
        if not 1 <= self.max_values_per_column <= 20:
            raise ValueError("max_values_per_column must be between 1 and 20")
        if not 16 <= self.max_value_chars <= 256:
            raise ValueError("max_value_chars must be between 16 and 256")
        if self.max_bytes_per_table < 1_024:
            raise ValueError("max_bytes_per_table must be at least 1024")
        if self.max_bytes_per_job < self.max_bytes_per_table:
            raise ValueError("max_bytes_per_job must cover one table budget")


@dataclass(frozen=True)
class SampledColumn:
    name: str
    data_type: str
    native_type: str
    values: tuple[object | None, ...]


@dataclass(frozen=True)
class SampledRelation:
    schema: str
    name: str
    estimated_row_count: int | None
    columns: tuple[SampledColumn, ...]


@dataclass(frozen=True)
class MaskedSample:
    masked_value: str
    value_type: str
    byte_count: int


@dataclass(frozen=True)
class ColumnProfileResult:
    name: str
    data_type: str
    sample_row_count: int
    non_null_count: int
    estimated_row_count: int | None
    sample_null_rate: float | None
    sampled_distinct_count: int | None
    minimum_value: str | None
    maximum_value: str | None
    minimum_length: int | None
    maximum_length: int | None
    average_length: float | None
    sensitivity_type: str | None
    sensitivity_confidence: float
    sensitivity_reasons: tuple[str, ...]
    metric_sources: dict[str, str]
    samples: tuple[MaskedSample, ...]
    skipped_reason: str | None = None


@dataclass(frozen=True)
class RelationProfileResult:
    schema: str
    name: str
    estimated_row_count: int | None
    columns: tuple[ColumnProfileResult, ...]
    sample_bytes: int
    budget_exhausted: bool


@dataclass(frozen=True)
class ProfileDocument:
    relations: tuple[RelationProfileResult, ...]
    sample_count: int
    sample_bytes: int
    budget_exhausted: bool
