from app.auth import KEY_PREFIX, display_prefix, generate_api_key, hash_key


def test_generate_api_key_has_expected_prefix_and_is_unique():
    key1 = generate_api_key()
    key2 = generate_api_key()

    assert key1.startswith(KEY_PREFIX)
    assert key2.startswith(KEY_PREFIX)
    assert key1 != key2
    assert len(key1) > len(KEY_PREFIX) + 20


def test_hash_key_is_deterministic_and_distinguishes_inputs():
    assert hash_key("abc") == hash_key("abc")
    assert hash_key("abc") != hash_key("xyz")
    assert hash_key("abc") != "abc"


def test_display_prefix_truncates_and_hides_rest_of_key():
    key = generate_api_key()

    shown = display_prefix(key)

    assert shown.startswith(KEY_PREFIX)
    assert shown.endswith("...")
    assert len(shown) < len(key)
