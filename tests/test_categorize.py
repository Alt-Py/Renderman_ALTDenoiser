from rman_denoiser.core import categorize


def test_category_of_known_names():
    assert categorize.category_of("Ci") == "Beauty"
    assert categorize.category_of("L_sun") == "Lighting"
    assert categorize.category_of("diffuse") == "Diffuse / Specular"
    assert categorize.category_of("Specular") == "Diffuse / Specular"
    assert categorize.category_of("albedo") == "Utility"
    assert categorize.category_of("Ci_variance") == "Diagnostic"
    assert categorize.category_of("weird_custom_aov") == "Other"


def test_lighting_beats_diffuse_specular():
    assert categorize.category_of("L_diffuse") == "Lighting"


def test_group_aovs_buckets_and_order():
    aovs = ["Ci", "diffuse", "specular", "a", "albedo", "Ci_variance",
            "L_custom", "L_night", "L_sun", "L_tomocco"]
    groups = categorize.group_aovs(aovs)
    names = [g for g, _ in groups]
    assert names == ["Beauty", "Lighting", "Diffuse / Specular", "Utility", "Diagnostic"]
    d = dict(groups)
    assert d["Beauty"] == ["Ci"]
    assert d["Lighting"] == ["L_custom", "L_night", "L_sun", "L_tomocco"]   # input order kept
    assert d["Diffuse / Specular"] == ["diffuse", "specular"]


def test_group_aovs_drops_empty_and_handles_other():
    groups = categorize.group_aovs(["Ci", "myCustomThing"])
    assert [g for g, _ in groups] == ["Beauty", "Other"]
    assert dict(groups)["Other"] == ["myCustomThing"]


def test_group_aovs_empty():
    assert categorize.group_aovs([]) == []
