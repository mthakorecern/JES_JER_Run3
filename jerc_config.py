#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

RUN3_YEARS = ("2022", "2023", "2024", "2025", "2026")

DEFAULT_METADATA_BASE = "/afs/hep.wisc.edu/home/mithakor/HH_bb_tautau_Analysis/JEC_JER/CMSSW_15_0_5/src/JEC_JER/metadata/"

# CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
# AK4_CONFIG = os.path.join(CONFIG_DIR, "JecConfigAK4.json")
# AK8_CONFIG = os.path.join(CONFIG_DIR, "JecConfigAK8.json")
AK4_CONFIG = "JecConfigAK4.json"
AK8_CONFIG = "JecConfigAK8.json"


@dataclass(frozen=True)
class DataEra:
    year: str
    run_era: str
    campaign: str
    config_era: str


@lru_cache(maxsize=None)
def load_json(path: str) -> dict:
    """Load and cache a JSON file."""

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def infer_data_era(input_file: str, requested_year: Optional[str] = None) -> DataEra:
    match = re.search(r"Run(20(?:22|23|24|25|26))([A-Z])", input_file)

    if not match:
        raise ValueError(
            "Could not infer the data era from the filename. Expected a token such as Run2022C, Run2023D, Run2024G, Run2025C, or Run2026B.")

    year = match.group(1)
    era = match.group(2)

    if requested_year and year != str(requested_year):
        raise ValueError(f"Filename says Run{year}{era}, but --year={requested_year} was requested.")

    if year == "2022":
        if era in ("C", "D"):
            campaign = "2022Pre"
        elif era in ("E", "F", "G"):
            campaign = "2022Post"
        else:
            raise ValueError(f"Unsupported 2022 data era: {era}. Expected C/D or E/F/G.")

    elif year == "2023":
        if era in ("B", "C"):
            campaign = "2023Pre"
        elif era == "D":
            campaign = "2023Post"
        else:
            raise ValueError(f"Unsupported 2023 data era: {era}.Expected B/C or D.")

    else:
        # The supplied configuration JSONs use one correction campaign
        # for all eras in 2024 and 2025.
        #
        # The same convention is reserved for 2026 once genuine 2026
        # configuration entries are provided.
        campaign = year

    return DataEra(year=year, run_era=era, campaign=campaign, config_era=f"Era{campaign}All",)


def campaign_for_mc(year: str, input_file: str) -> str:
    year = str(year)
    name = input_file.lower()

    if year == "2022":
        post_tokens = (
            "summer22ee",
            "2022post",
            "postee",
            "post_ee",
        )

        if any(token in name for token in post_tokens):
            return "2022Post"

        return "2022Pre"

    if year == "2023":
        post_tokens = (
            "summer23bpix",
            "2023post",
            "postbpix",
            "post_bpix",
        )

        if any(token in name for token in post_tokens):
            return "2023Post"

        return "2023Pre"

    if year in ("2024", "2025", "2026"):
        return year

    raise ValueError(
        f"Only Run-3 years are supported; received year={year}."
    )


def config_path(kind: str) -> str:
    """Return the AK4 or AK8 configuration path."""

    kind = kind.upper()

    if kind == "AK4":
        return AK4_CONFIG

    if kind == "AK8":
        return AK8_CONFIG

    raise ValueError(f"Unknown jet kind: {kind}")


def resolve_jerc_json(configured_path: str, year: str, kind: str) -> str:
    kind = kind.upper()

    if kind == "AK4":
        filename = "jet_jerc.json.gz"
    elif kind == "AK8":
        filename = "fatJet_jerc.json.gz"
    else:
        raise ValueError(f"Unknown jet kind: {kind}")
    
    # local_path = os.path.join(DEFAULT_METADATA_BASE, year, filename)
    local_path = filename

    
    if os.path.exists(local_path):
        # print(f"localpath {local_path}")
        return local_path

    return configured_path


def get_campaign_config(kind: str, campaign: str) -> dict:
    # print(f"Using {kind} config file")
    cfg = load_json(config_path(kind))

    if campaign not in cfg:
        raise RuntimeError(
            f"No {kind} JERC configuration for campaign '{campaign}'. "
            f"Available entries: {', '.join(cfg.keys())}. "
            "For 2026, add a genuine 2026 entry to both "
            "JecConfigAK4.json and JecConfigAK8.json."
        )

    return cfg[campaign]