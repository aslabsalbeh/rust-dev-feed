from scripts.relevance import (
    RELEVANCE_THRESHOLD,
    filter_player_relevant_commits,
    player_relevance_score,
)


def commit(message, branch="main"):
    return {"id": 1, "branch": branch, "message": message}


def assert_relevant(message, branch="main"):
    score = player_relevance_score(commit(message, branch))
    assert score >= RELEVANCE_THRESHOLD, (message, score)


def assert_not_relevant(message, branch="main"):
    score = player_relevance_score(commit(message, branch))
    assert score < RELEVANCE_THRESHOLD, (message, score)


def test_grenade_stack_size_change_is_relevant():
    assert_relevant(
        "Reduced F1 Grenade, Bee Grenade, Flashbang and Molotov stack sizes from 5 to 3"
    )


def test_sam_drone_buff_is_relevant():
    assert_relevant(
        "WIP SAM site buffs: proximity fuse, lead drones at 2.25x speed, "
        "destroy drone-dropped explosives mid-air"
    )


def test_code_lock_upkeep_change_is_relevant():
    assert_relevant(
        "Group upkeep modifier now counts players authed on code locks controlled by the TC",
        "main/tc_auth_group_tests",
    )




def test_heavy_plate_helmet_voice_muffling_is_relevant():
    assert_relevant(
        "In game player voices are now also muffled by heavy plate helmet\n"
        "Increased volume reduction (was 2400, now 1800)",
        "main/heavy_helmet_audio",
    )


def test_medieval_ak_material_tweak_is_not_relevant():
    assert_not_relevant(
        "Medieval AK gem material tweak: fixed refraction scale 75cm -> 2cm, "
        "corundum IOR, proper transmittance - reads as gemstone instead of grey glass",
        "main/prop_optimisations",
    )


def test_clothing_ao_vram_optimization_is_not_relevant():
    assert_not_relevant(
        "Clothing AO pass: capped 57 maps 2048 -> 512/1024, ~120MB VRAM saved "
        "with no visual difference",
        "main/texture_optimisations_2026/character",
    )


def test_animal_ao_vram_optimization_is_not_relevant():
    assert_not_relevant(
        "Animal AO caps: croc/stag/bears/panther/shark/wolf/chicken -> 1024/512, "
        "a further 17.5MB VRAM saved",
        "main/texture_optimisations_2026/character",
    )

def test_font_atlas_is_not_relevant():
    assert_not_relevant("Updated dynamic font atlas glyph generation")


def test_radial_blur_is_not_relevant():
    assert_not_relevant("Adjusted radial blur and vignette rendering")


def test_ao_texture_is_not_relevant():
    assert_not_relevant("Reduced AO texture resolution for memory savings")


def test_navmesh_door_performance_is_not_relevant():
    assert_not_relevant(
        "Navmesh now accounts for opening and closing doors without a full rebuild "
        "and improves door-handling performance"
    )


def test_third_person_magazine_drop_is_not_relevant():
    assert_not_relevant(
        "Ammunition magazines now drop correctly in third-person for Abyss AK, "
        "Ice AK and Space LR300"
    )


def test_pool_ball_velocity_creep_is_not_relevant():
    assert_not_relevant(
        "Fixed pool ball velocity creep between shots, ensuring proper ball movement"
    )


def test_duplicate_unsubscribe_disconnect_flow_is_not_relevant():
    assert_not_relevant(
        "Fixed disconnect flow to prevent duplicate unsubscribe errors when leaving servers"
    )


def test_head_icon_render_order_is_not_relevant():
    assert_not_relevant(
        "Adjusted head icon rendering so icons now appear in front of the player character"
    )


def test_idle_animation_jitter_is_not_relevant():
    assert_not_relevant(
        "Resolved multiple idle animations playing simultaneously, eliminating jitter "
        "and allowing reaction animations to trigger properly"
    )


def test_real_disconnect_exploit_is_still_relevant():
    assert_relevant(
        "Fixed disconnect exploit allowing players to duplicate loot from storage"
    )


def test_meaningful_npc_behavior_change_is_still_relevant():
    assert_relevant(
        "Scientists now open doors while pursuing players and can continue attacking"
    )


def test_filter_keeps_signal_and_drops_polish():
    commits = [
        commit("Reduced grenade stack size from 5 to 3"),
        {**commit("Fixed pool ball velocity creep between shots"), "id": 2},
        {**commit("SAM sites now destroy drone-dropped explosives"), "id": 3},
        {**commit("Adjusted head icon rendering order"), "id": 4},
    ]
    result = filter_player_relevant_commits(commits)
    ids = {item["id"] for item in result}
    assert ids == {1, 3}
