import uuid

import pytest
from pydantic import ValidationError

from packages.shared_contracts.queries import QueryFilter, SemanticQueryRequest


def test_protocol_rejects_ambiguous_filter_shapes() -> None:
    with pytest.raises(ValidationError):
        QueryFilter(dimension="status", operator="between", value=[1])
    with pytest.raises(ValidationError):
        QueryFilter(dimension="status", operator="eq", value=[1])


def test_protocol_caps_result_limit() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryRequest(semantic_model_id=uuid.uuid4(), metrics=["output"], limit=1001)
