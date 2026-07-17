"""Unit tests for audio-disclosure recovery. Pure functions, no network/docker.

The negative cases carry the weight. Typing a call *intimation* as a transcript
is how 157 of 453 staging "transcripts" ended up being letterheads; this path
must not repeat that by transcribing anything that merely says "conference call".
"""
from __future__ import annotations

from nidp.services.document_parser.audio_extractor import (
    find_media_urls,
    looks_like_audio_disclosure,
)

# The real GROWW filing this feature was built from (15-Jul-2026), trimmed.
GROWW_LETTER = """
Billionbrains Garage Ventures Limited
Registered Office: Vaishnavi Tech Park, Bengaluru 560103
CIN: L72900KA2018PLC109343
July 15, 2026
To, The Listing Department, BSE Limited     Scrip code: 544603
To, The Listing Department, National Stock Exchange of India Ltd.  Symbol: GROWW
Sub: Audio recording of earnings conference call for Analysts and Investors
Ref: Disclosure under Part A of Regulation 30 of SEBI (Listing Obligations and
Disclosure Requirements) Regulations, 2015
Pursuant to Part A of Regulation 30, the Audio recording of Conference Call for
Analysts and Investors held on July 15, 2026, is available on the website of the
Company, the link of the same is stated herein-below:
https://resources.groww.in/web-assets/media-library/2026/7/Q1%20FY27%20Earnings%20Call%20Replay.mp3
Kindly take the same on record and oblige.
"""


def test_detects_the_real_audio_disclosure_letter():
    assert looks_like_audio_disclosure(GROWW_LETTER)


def test_extracts_the_media_url_from_the_real_letter():
    urls = find_media_urls(GROWW_LETTER)
    assert urls == [
        "https://resources.groww.in/web-assets/media-library/2026/7/"
        "Q1%20FY27%20Earnings%20Call%20Replay.mp3"
    ]


def test_works_for_any_issuer_and_any_host():
    # Nothing may key off Groww, its CDN, or its filename.
    for host, ext in [("https://www.acme-industries.co.in/ir/q2-call.mp3", ".mp3"),
                      ("https://cdn.someamc.com/earnings/FY27Q1.m4a", ".m4a"),
                      ("https://media.bank.in/investor/replay.wav", ".wav")]:
        letter = f"Sub: Audio recording of the earnings conference call\nLink: {host}"
        assert looks_like_audio_disclosure(letter)
        assert find_media_urls(letter) == [host]


def test_a_call_INTIMATION_is_not_an_audio_disclosure():
    # Filed days BEFORE the call. No recording exists. This is precisely the
    # false positive that made 35% of typed transcripts letterheads.
    intimation = """
    Sub: Intimation of earnings conference call for Analysts and Investors
    We wish to inform you that a conference call is scheduled on July 15, 2026
    at 4:00 PM IST. The dial-in details are provided below.
    """
    assert not looks_like_audio_disclosure(intimation)


def test_an_agm_recording_notice_without_a_call_is_not_matched():
    # 'audio/recording' alone must not trigger — AGM notices say this constantly.
    agm = "Sub: Notice of AGM. An audio recording of the proceedings will be kept."
    assert not looks_like_audio_disclosure(agm)


def test_non_media_links_are_ignored():
    letter = GROWW_LETTER.replace(
        "https://resources.groww.in/web-assets/media-library/2026/7/"
        "Q1%20FY27%20Earnings%20Call%20Replay.mp3",
        "https://www.groww.in/investor-relations")
    assert looks_like_audio_disclosure(letter)   # still the right letter shape
    assert find_media_urls(letter) == []         # but nothing to transcribe


def test_trailing_punctuation_is_stripped():
    # PDFs habitually glue a full stop onto the URL's last character.
    letter = "Audio recording of the conference call: https://x.co/call.mp3."
    assert find_media_urls(letter) == ["https://x.co/call.mp3"]


def test_query_strings_and_fragments_do_not_defeat_extension_matching():
    letter = "Audio recording of the earnings call at https://x.co/a/call.mp3?t=1&x=2"
    assert find_media_urls(letter) == ["https://x.co/a/call.mp3?t=1&x=2"]


def test_duplicate_urls_are_deduped_preserving_order():
    letter = ("Audio recording of the conference call. https://x.co/1.mp3 "
              "and again https://x.co/1.mp3 plus https://x.co/2.mp3")
    assert find_media_urls(letter) == ["https://x.co/1.mp3", "https://x.co/2.mp3"]


def test_empty_and_none_text_are_safe():
    assert not looks_like_audio_disclosure("")
    assert not looks_like_audio_disclosure(None)
    assert find_media_urls("") == []
    assert find_media_urls(None) == []
