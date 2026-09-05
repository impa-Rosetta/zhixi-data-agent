import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from packages.connectors.profiling import (
    ColumnProfileResult,
    MaskedSample,
    ProfileDocument,
    RelationProfileResult,
    SampledColumn,
    SampledRelation,
    SamplingBudget,
)

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_CN_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{15,19}(?!\d)")
_TOKEN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
_CN_ID = re.compile(r"\d{17}[0-9Xx]")
_BANK_CARD = re.compile(r"\d{13,19}")
_BLOCKED_TYPES = frozenset({"binary", "json", "geospatial", "unknown", "object", "array"})
_BLOCKED_NATIVE_MARKERS = ("blob", "bytea", "binary", "varbinary", "geometry", "geography")

_NAME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("password", ("password", "passwd", "pwd", "passcode", "密码", "口令")),
    (
        "secret_token",
        (
            "api_key",
            "apikey",
            "access_key",
            "secret_key",
            "private_key",
            "token",
            "密钥",
            "令牌",
        ),
    ),
    ("email", ("email", "e_mail", "邮箱", "电子邮件")),
    ("phone", ("phone", "mobile", "telephone", "tel_no", "手机号", "电话")),
    (
        "national_id",
        ("id_card", "idcard", "identity_no", "national_id", "身份证", "证件号"),
    ),
    ("bank_card", ("bank_card", "card_number", "card_no", "银行卡", "银行卡号")),
)


@dataclass(frozen=True)
class SensitivityMatch:
    sensitivity_type: str | None
    confidence: float
    reasons: tuple[str, ...]
    sample_allowed: bool


def _normalized_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "_", value.casefold()).strip("_")


def _name_match(column_name: str) -> SensitivityMatch | None:
    normalized = _normalized_name(column_name)
    padded = f"_{normalized}_"
    for sensitivity_type, markers in _NAME_RULES:
        for marker in markers:
            normalized_marker = _normalized_name(marker)
            if normalized == normalized_marker or f"_{normalized_marker}_" in padded:
                return SensitivityMatch(
                    sensitivity_type,
                    0.98,
                    (f"name:{normalized_marker}",),
                    False,
                )
    return None


def _valid_cn_id(value: str) -> bool:
    if _CN_ID.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value[6:14], "%Y%m%d")
    except ValueError:
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    total = sum(int(digit) * weight for digit, weight in zip(value[:17], weights, strict=True))
    return checks[total % 11] == value[-1].upper()


def _valid_luhn(value: str) -> bool:
    if _BANK_CARD.fullmatch(value) is None or len(set(value)) == 1:
        return False
    total = 0
    parity = len(value) % 2
    for index, character in enumerate(value):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _value_match(value: object) -> SensitivityMatch | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    compact_digits = re.sub(r"[ -]", "", stripped)
    if _EMAIL.fullmatch(stripped):
        return SensitivityMatch("email", 0.99, ("value:email",), False)
    if _valid_cn_id(stripped):
        return SensitivityMatch("national_id", 1.0, ("value:cn_id_checksum",), False)
    if _CN_PHONE.fullmatch(stripped):
        return SensitivityMatch("phone", 0.99, ("value:cn_mobile",), False)
    if _valid_luhn(compact_digits):
        return SensitivityMatch("bank_card", 1.0, ("value:luhn",), False)
    if _TOKEN.fullmatch(stripped):
        return SensitivityMatch("secret_token", 1.0, ("value:token_format",), False)
    return None


def detect_sensitivity(column: SampledColumn) -> SensitivityMatch:
    portable_type = column.data_type.casefold()
    native_type = column.native_type.casefold()
    if portable_type in _BLOCKED_TYPES or any(
        marker in native_type for marker in _BLOCKED_NATIVE_MARKERS
    ):
        return SensitivityMatch("unsupported_type", 1.0, ("type:sample_blocked",), False)
    name_match = _name_match(column.name)
    if name_match is not None:
        return name_match
    for value in column.values:
        if value is None:
            continue
        value_match = _value_match(value)
        if value_match is not None:
            return value_match
    return SensitivityMatch(None, 0.0, (), True)


def mask_text(value: str) -> str:
    masked = _TOKEN.sub("[TOKEN]", value)
    masked = _EMAIL.sub("[EMAIL]", masked)
    masked = _CN_PHONE.sub("[PHONE]", masked)
    return _LONG_NUMBER.sub("[NUMBER]", masked)


def _stringify(value: object) -> tuple[str, str] | None:
    if isinstance(value, str):
        return mask_text(value), "string"
    if isinstance(value, bool):
        return ("true" if value else "false"), "boolean"
    if isinstance(value, (int, Decimal)):
        return str(value), "number"
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return str(value), "number"
    if isinstance(value, datetime):
        return value.isoformat(), "datetime"
    if isinstance(value, date):
        return value.isoformat(), "date"
    if isinstance(value, (dict, list)):
        return mask_text(json.dumps(value, ensure_ascii=False, sort_keys=True)), "json"
    return mask_text(str(value)), type(value).__name__[:32]


def _canonical(value: object) -> str:
    serialized = _stringify(value)
    if serialized is None:
        return type(value).__name__
    return f"{serialized[1]}:{serialized[0]}"


def _truncate(value: str, *, max_chars: int, max_bytes: int | None = None) -> str:
    truncated = value[:max_chars]
    if max_bytes is None:
        return truncated
    encoded = truncated.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore")


def _ranges(
    values: tuple[object, ...], max_chars: int
) -> tuple[str | None, str | None, int | None, int | None, float | None]:
    numeric: list[Decimal] = []
    temporal: list[date | datetime] = []
    text_lengths: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float, Decimal)):
            try:
                converted = Decimal(str(value))
            except InvalidOperation:
                continue
            if converted.is_finite():
                numeric.append(converted)
        elif isinstance(value, (date, datetime)):
            temporal.append(value)
        elif isinstance(value, str):
            text_lengths.append(len(value))
    minimum: str | None = None
    maximum: str | None = None
    if numeric and len(numeric) == len(values):
        minimum = _truncate(str(min(numeric)), max_chars=max_chars)
        maximum = _truncate(str(max(numeric)), max_chars=max_chars)
    elif temporal and len(temporal) == len(values):
        serialized = [item.isoformat() for item in temporal]
        minimum = _truncate(min(serialized), max_chars=max_chars)
        maximum = _truncate(max(serialized), max_chars=max_chars)
    if not text_lengths:
        return minimum, maximum, None, None, None
    return (
        minimum,
        maximum,
        min(text_lengths),
        max(text_lengths),
        sum(text_lengths) / len(text_lengths),
    )


def _profile_column(
    column: SampledColumn,
    *,
    estimated_row_count: int | None,
    budget: SamplingBudget,
    table_bytes: int,
    job_bytes: int,
) -> tuple[ColumnProfileResult, int, bool]:
    values = column.values[: budget.max_rows_per_table]
    non_null = tuple(value for value in values if value is not None)
    sample_null_rate = (len(values) - len(non_null)) / len(values) if values else None
    distinct_count = len({_canonical(value) for value in non_null}) if non_null else 0
    try:
        sensitivity = detect_sensitivity(
            SampledColumn(column.name, column.data_type, column.native_type, values)
        )
    except Exception:
        sensitivity = SensitivityMatch("unknown_sensitive", 1.0, ("detector:error",), False)
    minimum: str | None = None
    maximum: str | None = None
    minimum_length: int | None = None
    maximum_length: int | None = None
    average_length: float | None = None
    samples: list[MaskedSample] = []
    consumed = 0
    exhausted = False
    skipped_reason = None
    if sensitivity.sample_allowed:
        minimum, maximum, minimum_length, maximum_length, average_length = _ranges(
            non_null, budget.max_value_chars
        )
        seen: set[str] = set()
        for value in non_null:
            if len(samples) >= budget.max_values_per_column:
                break
            serialized = _stringify(value)
            if serialized is None:
                continue
            masked_value, value_type = serialized
            remaining = min(
                budget.max_bytes_per_table - table_bytes - consumed,
                budget.max_bytes_per_job - job_bytes - consumed,
            )
            if remaining <= 0:
                exhausted = True
                break
            masked_value = _truncate(
                masked_value, max_chars=budget.max_value_chars, max_bytes=remaining
            )
            if not masked_value or masked_value in seen:
                continue
            byte_count = len(masked_value.encode("utf-8"))
            seen.add(masked_value)
            samples.append(MaskedSample(masked_value, value_type, byte_count))
            consumed += byte_count
            if (
                table_bytes + consumed >= budget.max_bytes_per_table
                or job_bytes + consumed >= budget.max_bytes_per_job
            ):
                exhausted = True
                break
    else:
        skipped_reason = (
            "unsupported_type"
            if sensitivity.sensitivity_type == "unsupported_type"
            else "sensitive"
        )
    metric_sources = {
        "estimated_row_count": "estimated",
        "sample_null_rate": "sampled",
        "sampled_distinct_count": "sampled",
    }
    if minimum is not None:
        metric_sources["range"] = "sampled"
    if minimum_length is not None:
        metric_sources["length"] = "sampled"
    return (
        ColumnProfileResult(
            name=column.name,
            data_type=column.data_type,
            sample_row_count=len(values),
            non_null_count=len(non_null),
            estimated_row_count=estimated_row_count,
            sample_null_rate=sample_null_rate,
            sampled_distinct_count=distinct_count,
            minimum_value=minimum,
            maximum_value=maximum,
            minimum_length=minimum_length,
            maximum_length=maximum_length,
            average_length=average_length,
            sensitivity_type=sensitivity.sensitivity_type,
            sensitivity_confidence=sensitivity.confidence,
            sensitivity_reasons=sensitivity.reasons,
            metric_sources=metric_sources,
            samples=tuple(samples),
            skipped_reason=skipped_reason,
        ),
        consumed,
        exhausted,
    )


def build_profile_document(
    relations: tuple[SampledRelation, ...], budget: SamplingBudget
) -> ProfileDocument:
    profiled_relations: list[RelationProfileResult] = []
    job_bytes = 0
    job_exhausted = False
    for relation in relations:
        table_bytes = 0
        table_exhausted = False
        columns: list[ColumnProfileResult] = []
        estimated_row_count = (
            relation.estimated_row_count
            if relation.estimated_row_count is not None and relation.estimated_row_count >= 0
            else None
        )
        for column in relation.columns:
            profile, consumed, exhausted = _profile_column(
                column,
                estimated_row_count=estimated_row_count,
                budget=budget,
                table_bytes=table_bytes,
                job_bytes=job_bytes,
            )
            columns.append(profile)
            table_bytes += consumed
            job_bytes += consumed
            table_exhausted = table_exhausted or exhausted
            if job_bytes >= budget.max_bytes_per_job:
                job_exhausted = True
        profiled_relations.append(
            RelationProfileResult(
                schema=relation.schema,
                name=relation.name,
                estimated_row_count=estimated_row_count,
                columns=tuple(columns),
                sample_bytes=table_bytes,
                budget_exhausted=table_exhausted,
            )
        )
    return ProfileDocument(
        relations=tuple(profiled_relations),
        sample_count=sum(
            len(column.samples) for relation in profiled_relations for column in relation.columns
        ),
        sample_bytes=job_bytes,
        budget_exhausted=job_exhausted
        or any(relation.budget_exhausted for relation in profiled_relations),
    )
