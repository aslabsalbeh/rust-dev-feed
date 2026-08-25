from scripts.summarize import player_relevance_score


def score(message):
    commit = {
        "id": 999999,
        "branch": "",
        "message": message,
        "created": "2026-08-25T12:00:00",
    }

    return player_relevance_score(commit)


def test_grenade_stack_size_change_is_relevant():
    message = (
        "Reduced stack size for F1s 5 > 3, "
        "Bee nades 5 > 3, Flashbangs 5 > 3, "
        "Molotovs 5 > 3"
    )

    assert score(message) >= 2


def test_sam_drone_buff_is_relevant():
    message = (
        "SAM site vs drone buffs wip: Missiles use a proximity "
        "fuse against drones, lead vs them without aim error at "
        "2.25x speed, and destroy drone-dropped explosives mid-air"
    )

    assert score(message) >= 2


def test_code_lock_upkeep_change_is_relevant():
    message = (
        "Group upkeep modifier now takes into account any unique "
        "players authed on a code lock. If a player is not authed "
        "on a TC but is authed on a code lock controlled by that "
        "TC then they will contribute to upkeep costs."
    )

    assert score(message) >= 2


def test_font_atlas_change_is_not_relevant():
    message = (
        "Increased icon-font atlas to 1024x1024 and switched "
        "to on-demand glyph generation."
    )

    assert score(message) < 2


def test_radial_blur_change_is_not_relevant():
    message = (
        "Radial blur added to the rendering pipeline and "
        "vignette effect toned down."
    )

    assert score(message) < 2


def test_ao_texture_change_is_not_relevant():
    message = (
        "Reduced AO texture resolution from 1024 to 512 "
        "for improved asset memory usage."
    )

    assert score(message) < 2
