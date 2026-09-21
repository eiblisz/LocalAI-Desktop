from app.ollama_resource_coordinator import (
    OWNER_EINSTEIN,
    OWNER_LOCALAI_DESKTOP,
    OWNER_MANUAL,
    OWNER_OTHER,
    OWNER_SCHEDULER,
    OWNER_UNKNOWN,
    STATE_ERROR,
    STATE_IDLE,
    STATE_INFERENCE_ACTIVE,
    STATE_MODEL_LOADING,
    STATE_RELEASING,
    STATE_RESERVED,
    STATE_STALE,
    ResourceLeaseStore,
)


def test_owner_and_state_contract_is_explicit():
    assert {
        OWNER_LOCALAI_DESKTOP,
        OWNER_EINSTEIN,
        OWNER_MANUAL,
        OWNER_SCHEDULER,
        OWNER_OTHER,
        OWNER_UNKNOWN,
    } == {
        "LOCALAI_DESKTOP",
        "EINSTEIN",
        "MANUAL",
        "SCHEDULER",
        "OTHER",
        "UNKNOWN",
    }
    assert {
        STATE_IDLE,
        STATE_RESERVED,
        STATE_MODEL_LOADING,
        STATE_INFERENCE_ACTIVE,
        STATE_RELEASING,
        STATE_STALE,
        STATE_ERROR,
    } == {
        "IDLE",
        "RESERVED",
        "MODEL_LOADING",
        "INFERENCE_ACTIVE",
        "RELEASING",
        "STALE",
        "ERROR",
    }


def test_unknown_ownership_is_never_destructive_authority(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")

    allowed, ownership = store.can_control_model(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
    )

    assert allowed is False
    assert ownership["owner"] == OWNER_UNKNOWN


def test_idle_desktop_lease_is_control_authority_for_same_owner(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=100,
        model_pid=200,
        request_id="req-1",
    )

    allowed, lease = store.can_control_model(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
    )

    assert allowed is True
    assert lease["model_pid"] == 200
    assert lease["request_id"] == "req-1"
    assert lease["start_time"]
    assert lease["last_heartbeat"]


def test_active_inference_is_not_free_vram_authority(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_INFERENCE_ACTIVE,
        owner_pid=100,
        model_pid=200,
    )

    allowed, _lease = store.can_control_model(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        allow_active=False,
    )
    explicit_kill_allowed, _lease = store.can_control_model(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        allow_active=True,
    )

    assert allowed is False
    assert explicit_kill_allowed is True


def test_foreign_active_lease_is_reported(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    store.upsert(
        owner=OWNER_EINSTEIN,
        owner_id="einstein:1",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_INFERENCE_ACTIVE,
        owner_pid=300,
        model_pid=400,
    )

    foreign = store.foreign_active_leases(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
    )

    assert len(foreign) == 1
    assert foreign[0]["owner"] == OWNER_EINSTEIN


def test_reconciliation_marks_stale_without_kill_authority(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=100,
        model_pid=200,
    )

    changed = store.mark_stale(
        "qwen3-coder:30b-a3b-q8_0",
        detail="no runner process exists",
    )

    assert changed
    ownership = store.ownership("qwen3-coder:30b-a3b-q8_0")
    assert ownership["owner"] == OWNER_UNKNOWN
    assert ownership["state"] == STATE_STALE
    assert "no runner process" in ownership["detail"]
