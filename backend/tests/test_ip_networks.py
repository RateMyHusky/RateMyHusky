import fetch_ip_data
import ip_networks as ipn

RELAY = ["172.224.226.0/27,US,US-MA,Boston,", "2a02:26f7:b3c0:4000::/64,US,US-MA,Boston,",
         "172.224.226.32/27,US,US-MA,Boston,"]
ASN = {"8.8.8.8": {"asn": "AS15169", "as_domain": "google.com"},
       "100.64.1.1": {"asn": "AS21928", "as_domain": "t-mobile.com"},
       "73.1.2.3": {"asn": "AS7922", "as_domain": "comcast.net"},
       "172.224.226.5": {"asn": "AS36183", "as_domain": "akamai.com"}}


def make(asn=ASN):
    return ipn.NetworkIndex(asn.get if asn is not None else None, ipn.parse_relay_ranges(RELAY))


def test_network_types():
    idx = make()
    assert idx.network_type("129.10.9.9") == "campus"
    assert idx.network_type("155.33.1.1") == "campus"
    assert idx.network_type("::ffff:129.10.1.2") == "campus"
    assert idx.network_type("172.224.226.5") == "relay"
    assert idx.network_type("172.224.226.40") == "relay"
    assert idx.network_type("2a02:26f7:b3c0:4000::1") == "relay"
    assert idx.network_type("8.8.8.8") == "datacenter"
    assert idx.network_type("100.64.1.1") == "mobile"
    assert idx.network_type("73.1.2.3") == "other"
    assert idx.network_type(None) == "unknown"
    assert idx.network_type("junk") == "unknown"


def test_campus_asn_is_campus():
    idx = ipn.NetworkIndex({"9.9.9.9": {"asn": "AS156", "as_domain": "northeastern.edu"}}.get,
                           ipn.parse_relay_ranges([]))
    assert idx.network_type("9.9.9.9") == "campus"


def test_adjacent_relay_ranges_merge():
    v4s, v4e, v6s, v6e = ipn.parse_relay_ranges(RELAY)
    assert len(v4s) == len(v4e) == 1
    assert len(v6s) == len(v6e) == 1


def test_no_asn_database():
    idx = make(None)
    assert idx.network_type("73.1.2.3") == "unknown"
    assert idx.network_type("129.10.9.9") == "campus"
    assert idx.network_type("172.224.226.5") == "relay"


def test_load_index_empty_dir_does_not_raise(tmp_path):
    idx = ipn.load_index(str(tmp_path))
    assert idx.network_type("73.1.2.3") == "unknown"
    assert idx.network_type("129.10.9.9") == "campus"


def test_load_index_broken_files_do_not_raise(tmp_path):
    (tmp_path / "ipinfo_lite.mmdb").write_bytes(b"not a database")
    (tmp_path / "relay.csv").write_bytes(b"\xff\xfe garbage")
    assert ipn.load_index(str(tmp_path)).network_type("73.1.2.3") == "unknown"


def test_load_index_reads_relay_csv(tmp_path):
    (tmp_path / "relay.csv").write_text("\n".join(RELAY))
    assert ipn.load_index(str(tmp_path)).network_type("172.224.226.40") == "relay"


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield b"da"
        yield b"ta"


def test_fetch_without_token_skips_ipinfo(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IPINFO_TOKEN", raising=False)
    monkeypatch.setenv("IP_DATA_DIR", str(tmp_path))
    urls = []
    monkeypatch.setattr(fetch_ip_data.http_requests, "get",
                        lambda url, **kw: urls.append(url) or _Resp())
    assert fetch_ip_data.main() == 0
    assert all("ipinfo.io" not in u for u in urls) and len(urls) == 1
    assert (tmp_path / "relay.csv").read_bytes() == b"data"
    assert "skipped: IPINFO_TOKEN not set" in capsys.readouterr().out


def test_fetch_keeps_a_file_fetched_in_the_last_day(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IPINFO_TOKEN", raising=False)
    monkeypatch.setenv("IP_DATA_DIR", str(tmp_path))
    (tmp_path / "relay.csv").write_bytes(b"old")
    monkeypatch.setattr(fetch_ip_data.http_requests, "get",
                        lambda url, **kw: (_ for _ in ()).throw(AssertionError("fetched")))
    assert fetch_ip_data.main() == 0
    assert (tmp_path / "relay.csv").read_bytes() == b"old"
    assert "relay.csv kept" in capsys.readouterr().out


def test_fetch_gives_up_after_the_deadline(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IPINFO_TOKEN", raising=False)
    monkeypatch.setenv("IP_DATA_DIR", str(tmp_path))
    clock = iter([0, 0, fetch_ip_data.DEADLINE + 1])
    monkeypatch.setattr(fetch_ip_data.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(fetch_ip_data.http_requests, "get", lambda url, **kw: _Resp())
    assert fetch_ip_data.main() == 0
    assert not (tmp_path / "relay.csv").exists()
    assert "relay.csv failed: not done after" in capsys.readouterr().out


def test_fetch_failure_exits_zero_and_hides_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IPINFO_TOKEN", "SECRET123")
    monkeypatch.setenv("IP_DATA_DIR", str(tmp_path))

    def boom(url, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(fetch_ip_data.http_requests, "get", boom)
    assert fetch_ip_data.main() == 0
    out = capsys.readouterr().out
    assert "failed: down" in out and "SECRET123" not in out


def test_asn_lookup_error_is_contained():
    def boom(ip):
        raise ValueError("IPv6 in IPv4-only database")
    idx = ipn.NetworkIndex(boom, ipn.parse_relay_ranges(RELAY))
    assert idx.network_type("73.1.2.3") == "other"
    assert idx.network_type("129.10.9.9") == "campus"


def test_load_index_logs_missing_files(tmp_path, capsys):
    ipn.load_index(str(tmp_path))
    out = capsys.readouterr().out
    assert "ipinfo_lite.mmdb missing" in out and "relay.csv missing" in out
