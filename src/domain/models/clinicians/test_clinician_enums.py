import pytest

from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    CERTIFICATION_TYPES_LABELS,
    EDUCATION_TYPES,
    EDUCATION_TYPES_LABELS,
    LICENSE_TYPES,
    LICENSE_TYPES_LABELS,
)


@pytest.mark.parametrize(
    "vocab,labels",
    [
        (LICENSE_TYPES, LICENSE_TYPES_LABELS),
        (EDUCATION_TYPES, EDUCATION_TYPES_LABELS),
        (CERTIFICATION_TYPES, CERTIFICATION_TYPES_LABELS),
    ],
)
def test_labels_cover_vocab(vocab, labels):
    assert set(vocab) == set(labels.keys())
