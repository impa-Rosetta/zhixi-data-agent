import pytest

from packages.modeling.data import ModelDataError, prepare_training_data
from tests.test_modeling_data import fixture


@pytest.mark.parametrize("cell", [True, {}, "9"])
def test_invalid_regression_cells_even_with_valid_digest(cell):
    source, spec = fixture([[i, "A", cell if i == 0 else i] for i in range(40)])
    with pytest.raises(ModelDataError):
        prepare_training_data(spec, lambda _: source)


def test_row_budget_is_not_silently_trimmed():
    source, spec = fixture([[i, "A", i] for i in range(20_001)])
    with pytest.raises(ModelDataError, match="model.data_limit"):
        prepare_training_data(spec, lambda _: source)


def test_empty_feature_is_not_filled_from_target():
    source, spec = fixture([[None, "A", i] for i in range(40)])
    with pytest.raises(ModelDataError, match="model.empty_field"):
        prepare_training_data(spec, lambda _: source)


def test_missing_requested_field_is_not_guessed():
    source, spec = fixture()
    spec = spec.model_copy(update={"features": ("missing",)})
    with pytest.raises(ModelDataError, match="model.field_not_found"):
        prepare_training_data(spec, lambda _: source)
