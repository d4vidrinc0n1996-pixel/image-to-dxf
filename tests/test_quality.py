"""Regresión de calidad: foto sintética degradada (desenfoque, ruido, JPEG, luz desigual)."""
import numpy as np
import pytest

from app.vectorize import Options, vectorize
from tools.benchmark import iou, photo, reference, render

REF = reference()
GT = REF > 127


@pytest.mark.parametrize("seed", [0, 1])
def test_photo_quality(seed):
    vec = vectorize(photo(REF, seed), Options(colors=2))
    assert iou(render(vec, REF.shape), GT) > 0.95


def test_local_light_correction_helps():
    data = photo(REF, 0)
    on = iou(render(vectorize(data, Options(colors=2)), REF.shape), GT)
    off = iou(render(vectorize(data, Options(colors=2, adapt_light=False)), REF.shape), GT)
    assert on > off
