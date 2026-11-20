"""Tests for Telnet parsing helpers, satellites.xml names, and TV-only bouquets."""

from __future__ import annotations

from spidervip.channels.bouquets import parse_bouquet_files, parse_bouquets_index
from spidervip.channels.model import Channel
from spidervip.channels.satellites import (
    enrich_channels_with_satellite_names,
    parse_satellites_xml,
    position_from_namespace,
    position_label,
    tv_channels_only,
)
from spidervip.channels.telnet_ftp import TelnetClient, strip_ansi


def test_strip_ansi_removes_color_codes():
    raw = "\x1b[0;0m/data/gx/local/enigma_db/userbouquet.1.tv\x1b[m"
    assert strip_ansi(raw) == "/data/gx/local/enigma_db/userbouquet.1.tv"


def test_telnet_extract_output_ignores_echoed_command_and_prompt():
    text = (
        "PROMPT> ls -1 /tmp\n"
        "/tmp/a\n"
        "/tmp/b\n"
        'PROMPT> echo "MK""7""END"\n'
        "MK7END\n"
    )
    out = TelnetClient._extract_output(text, command="ls -1 /tmp", token="MK7END")
    assert out.splitlines() == ["/tmp/a", "/tmp/b"]


def test_telnet_extract_does_not_stop_on_echo_cmdline_without_contiguous_token():
    text = (
        "PROMPT> cat /x\n"
        "#NAME IRAN\n"
        "#SERVICE 1:0:1:1:1:1:1:0:0:0:\n"
        'PROMPT> echo "MK""7""END"\n'
        "MK7END\n"
    )
    out = TelnetClient._extract_output(text, command="cat /x", token="MK7END")
    assert "#NAME IRAN" in out
    assert "#SERVICE 1:0:1:1:1:1:1:0:0:0:" in out


def test_parse_tv_bouquets_ignore_radio_files():
    files = {
        "bouquets.tv": (
            '#NAME User - bouquets (TV)\n'
            '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.1.tv" ORDER BY bouquet\n'
        ),
        "bouquets.radio": (
            '#NAME User - bouquets (Radio)\n'
            '#SERVICE 1:7:2:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.1.radio" ORDER BY bouquet\n'
        ),
        "userbouquet.1.tv": "#NAME IRAN\n#SERVICE 1:0:1:1:2:3:4:0:0:0:\n",
        "userbouquet.1.radio": "#NAME IRAN\n#SERVICE 1:0:2:9:8:7:6:0:0:0:\n",
    }
    assert parse_bouquets_index(files["bouquets.radio"]) == []
    favs = parse_bouquet_files(files)
    assert len(favs) == 1
    assert favs[0].id == "1"
    assert favs[0].name == "IRAN"


def test_satellites_xml_maps_position_to_name():
    xml = """<?xml version="1.0"?>
<satellites>
  <sat name="Türksat 42.0E" flags="0" position="420"/>
  <sat name="7.0W Nilesat 201" flags="0" position="-70"/>
</satellites>
"""
    mapping = parse_satellites_xml(xml)
    assert mapping["42.0E"] == "Türksat 42.0E"
    assert mapping["7.0W"] == "7.0W Nilesat 201"
    assert position_label(260) == "26.0E"


def test_enrich_and_tv_filter():
    channels = [
        Channel(ref="a", name="A", satellite="Unknown", orbital_position="", namespace="01040000", service_type="TV"),
        Channel(ref="b", name="B", satellite="26.0E", orbital_position="26.0E", service_type="Radio"),
        Channel(ref="c", name="C", satellite="Unknown", orbital_position="", namespace="01a40000", service_type="TV"),
    ]
    enrich_channels_with_satellite_names(
        channels,
        {"26.0E": "Badr 26E", "42.0E": "Türksat 42.0E"},
    )
    assert channels[0].satellite == "Badr 26E"
    assert channels[0].orbital_position == "26.0E"
    assert channels[2].satellite == "Türksat 42.0E"
    tv = tv_channels_only(channels)
    assert [c.ref for c in tv] == ["a", "c"]


def test_position_from_namespace():
    assert position_from_namespace("01040000") == "26.0E"
    assert position_from_namespace("01a40000") == "42.0E"
