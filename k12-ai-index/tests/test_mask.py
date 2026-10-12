from k12aii.prompts import build_masked_prompt, mask_name


def test_mask_name():
    assert mask_name("Maple Grove Elementary School") == "[X] Elementary School"
    assert mask_name("Our Lady Of Good Counsel High School") == "Our Lady Of [X] High School"
    assert mask_name("Saint Mary Catholic Academy") == "Saint [X] Catholic Academy"
    assert mask_name("Christian Academy") == "Christian Academy"
    assert mask_name("Oakwood") == "[X]"


def test_masked_prompt_hides_city_and_name():
    p = build_masked_prompt({"school_name": "Maple Grove Elementary School", "city": "Springfield", "state": "IL"})
    assert "Maple" not in p and "Springfield" not in p and "[X] Elementary School" in p and "IL" in p
    assert "MUST give your single best answer" in p
