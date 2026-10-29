import rating_identity as ri

S = "s" * 32

def test_device_tokens_are_128_bit_hex_and_validated():
    t = ri.new_device_token()
    assert ri.valid_device_token(t) and len(t) == 32
    for bad in (None, "", "G" * 32, "a" * 31, "A" * 32, 123):
        assert not ri.valid_device_token(bad)

def test_keyed_hash_depends_on_kind_and_secret():
    assert ri.keyed_hash(S, "ip", "1.2.3.4") != ri.keyed_hash(S, "net", "1.2.3.4")
    assert ri.keyed_hash(S, "ip", "1.2.3.4") != ri.keyed_hash("t" * 32, "ip", "1.2.3.4")

def test_ip_prefix():
    assert ri.ip_prefix("129.10.5.77") == "129.10.5.0/24"
    assert ri.ip_prefix("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::/64"
    assert ri.ip_prefix("not-an-ip") is None

def test_opened_round_trip_and_fill_time():
    tok = ri.sign_opened(S, 1000, "d" * 64, minted=True)
    assert ri.read_opened(S, tok, "d" * 64, now=1042) == (42, True)

def test_opened_rejects_forgery_other_device_and_garbage():
    tok = ri.sign_opened(S, 1000, "d" * 64, minted=False)
    assert ri.read_opened(S, tok, "e" * 64, now=1042) == (None, False)
    assert ri.read_opened("t" * 32, tok, "d" * 64, now=1042) == (None, False)
    assert ri.read_opened(S, tok.replace("1000", "900", 1), "d" * 64, now=1042) == (None, False)
    head = tok.split(".")[:3]
    non_ascii = ".".join(head + ["é"])
    surrogate = ".".join(head + ["\ud800"])
    for junk in (None, "", "a.b.c", "x.1.y.z", non_ascii, surrogate):
        assert ri.read_opened(S, junk, "d" * 64, now=1042) == (None, False)
