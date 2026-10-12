import pandas as pd

from k12aii.baseline import predict


def test_name_rules():
    df = pd.DataFrame({"nces_id": list("abcd"), "school_name": ["Lincoln Elementary School", "St Mary Catholic High School",
                       "Grace Lutheran School", "Oak Grove High School"], "city": ["X"] * 4, "enrollment": [300.0] * 4})
    p = predict(df)
    assert list(p.sector) == ["public", "private", "private", "public"]
    assert list(p.level) == ["elementary", "high", "combined", "high"]
    assert list(p.religion) == ["none", "catholic", "other_religious", "none"]
