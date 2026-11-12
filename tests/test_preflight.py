import preflight
from _azcli import read_tfvars
from preflight import BLOCK, OK, WARN, check_policy, check_region

MODELS = [
    {
        "kind": "AIServices",
        "model": {
            "name": "gpt-4.1-mini",
            "version": "2025-04-14",
            "skus": [{"name": "GlobalStandard"}, {"name": "Standard"}],
        },
    }
]


def fake_az(models, usages):
    def _az_json(*args, **_):
        if args[:2] == ("cognitiveservices", "model"):
            return models
        if args[:2] == ("cognitiveservices", "usage"):
            return usages
        raise AssertionError(args)

    return _az_json


def usage(limit, current):
    return [
        {
            "name": {"value": "OpenAI.GlobalStandard.gpt-4.1-mini"},
            "limit": limit,
            "currentValue": current,
        }
    ]


def test_region_ok_when_offered_and_quota_free(monkeypatch):
    monkeypatch.setattr(preflight, "az_json", fake_az(MODELS, usage(50, 0)))
    c = check_region("eastus2", "gpt-4.1-mini", "2025-04-14", "GlobalStandard", 10)
    assert c.status == OK


def test_region_matches_quota_name_without_hyphen(monkeypatch):
    # Real Azure naming: model `gpt-4.1-mini`, quota `OpenAI.GlobalStandard.gpt4.1-mini`.
    quota = [
        {
            "name": {"value": "OpenAI.GlobalStandard.gpt4.1-mini"},
            "limit": 5000.0,
            "currentValue": 100.0,
        }
    ]
    monkeypatch.setattr(preflight, "az_json", fake_az(MODELS, quota))
    c = check_region("westus3", "gpt-4.1-mini", "2025-04-14", "GlobalStandard", 10)
    assert c.status == OK and "4900" in c.detail


def test_region_warns_when_model_is_legacy(monkeypatch):
    legacy = [{**MODELS[0], "model": {**MODELS[0]["model"], "lifecycleStatus": "Legacy"}}]
    monkeypatch.setattr(preflight, "az_json", fake_az(legacy, usage(50, 0)))
    c = check_region("canadacentral", "gpt-4.1-mini", "2025-04-14", "GlobalStandard", 10)
    assert c.status == WARN and "Legacy" in c.detail


def test_region_warns_on_partial_quota(monkeypatch):
    monkeypatch.setattr(preflight, "az_json", fake_az(MODELS, usage(50, 45)))
    c = check_region("eastus2", "gpt-4.1-mini", "2025-04-14", "GlobalStandard", 10)
    assert c.status == WARN and "model_capacity <= 5" in c.detail


def test_region_blocks_on_zero_quota(monkeypatch):
    monkeypatch.setattr(preflight, "az_json", fake_az(MODELS, usage(0, 0)))
    c = check_region("eastus2", "gpt-4.1-mini", "2025-04-14", "GlobalStandard", 10)
    assert c.status == BLOCK


def test_region_blocks_when_version_not_offered(monkeypatch):
    monkeypatch.setattr(preflight, "az_json", fake_az(MODELS, usage(50, 0)))
    c = check_region("eastus2", "gpt-4.1-mini", "2099-01-01", "GlobalStandard", 10)
    assert c.status == BLOCK and "not offered" in c.detail


def test_policy_check():
    assert check_policy("eastus2", None).status == "INFO"
    assert check_policy("EastUS2", ["eastus2"]).status == OK
    assert check_policy("westeurope", ["eastus2"]).status == BLOCK


def test_read_tfvars_scalars_only(tmp_path):
    p = tmp_path / "terraform.tfvars"
    p.write_text(
        'location = "swedencentral"  # comment\n'
        "model_capacity = 5\n"
        "assign_roles   = false\n"
        'tags = {\n  owner = "me"\n}\n',
        encoding="utf-8",
    )
    values = read_tfvars(p)
    assert values["location"] == "swedencentral"
    assert values["model_capacity"] == "5"
    assert values["assign_roles"] == "false"
    assert "tags" not in values
    assert read_tfvars(tmp_path / "missing.tfvars") == {}
