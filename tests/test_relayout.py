from relayout import relayout
from state import CategorySlot, State


def _state(slots: dict[str, list[int]], *, nav: int | None = None, info: int | None = None) -> State:
    return State(
        slots={k: CategorySlot(title=k, message_ids=v, content_hash="h") for k, v in slots.items()},
        nav_message_id=nav, nav_hash="n", info_message_id=info, info_hash="i",
    )


def test_new_categories_take_posts_in_channel_order():
    # Было: a=4, samsung=5, b=6, навигация 7; выбывший пост 10 ещё жив.
    state = _state({"a": [4], "samsung": [5], "b": [6]}, nav=7)
    result = relayout(state, ["a", "s1", "s2", "b"], {"s1": "Samsung S"}, reuse_ids=[10])

    assert [result.state.slots[k].message_ids for k in ["a", "s1", "s2", "b"]] == [[4], [5], [6], [7]]
    assert result.state.slots["s1"].title == "Samsung S"
    assert result.state.nav_message_id == 10
    assert result.unpin_message_id == 7
    assert result.leftover_ids == []


def test_hashes_are_reset_so_every_post_is_rewritten():
    result = relayout(_state({"a": [4]}, nav=5), ["a"], {})
    assert result.state.slots["a"].content_hash is None
    assert result.state.nav_hash is None


def test_categories_beyond_existing_posts_get_new_posts_and_nav_moves_to_end():
    state = _state({"a": [4]}, nav=5)
    result = relayout(state, ["a", "b", "c"], {})
    assert result.state.slots["b"].message_ids == [5]
    assert result.state.slots["c"].message_ids == []
    assert result.state.nav_message_id is None
    assert result.unpin_message_id == 5


def test_info_keeps_its_place_before_nav_when_posts_remain():
    state = _state({"a": [4], "b": [5]}, info=6, nav=7)
    result = relayout(state, ["a"], {})
    assert result.state.info_message_id == 5
    assert result.state.nav_message_id == 6
    assert result.leftover_ids == [7]


def test_unchanged_layout_keeps_nav_pinned():
    state = _state({"a": [4], "b": [5]}, nav=6)
    result = relayout(state, ["a", "b"], {})
    assert result.state.nav_message_id == 6
    assert result.unpin_message_id is None
