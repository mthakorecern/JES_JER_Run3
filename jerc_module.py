#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple
import correctionlib
import numpy as np
from PhysicsTools.NanoAODTools.postprocessing.framework.datamodel import Collection, Object
from PhysicsTools.NanoAODTools.postprocessing.framework.eventloop import Module
from jerc_config import campaign_for_mc, get_campaign_config, infer_data_era, resolve_jerc_json

MC_VARIATIONS = ("jesTotalUp", "jesTotalDown", "jerUp", "jerDown")

def _wrap_phi(phi: float) -> float:
    return math.atan2(math.sin(phi), math.cos(phi))

def _correction_inputs(correction) -> Sequence[Tuple[str, str]]:
    return tuple((item.name, str(item.type)) for item in correction.inputs)

def _evaluate(correction, values: Dict[str, object]):
    aliases = {
        "JetA": "area",
        "area": "area",
        "JetEta": "eta",
        "eta": "eta",
        "JetPhi": "phi",
        "phi": "phi",
        "JetPt": "pt",
        "pt": "pt",
        "Rho": "rho",
        "rho": "rho",
        "run": "run",
        "Run": "run",
        "systematic": "systematic",
        "Systematic": "systematic",
        "variation": "systematic",
        "Variation": "systematic",
    }

    arguments = []

    for input_name, _ in _correction_inputs(correction):
        key = aliases.get(input_name, input_name)

        if key not in values:
            raise KeyError(f"No value was provided for correction input. '{input_name}' in correction '{correction.name}'.")
        arguments.append(values[key])

    return correction.evaluate(*arguments)


def _stable_gaussian(run: int, lumi: int, event: int, index: int, salt: str) -> float:
    """
    Return a reproducible standard - normal random number. The random seed depends on the run, luminosity block, event number, jet index, and collection salt.
    """
    payload = (f"{run}:{lumi}:{event}:{index}:{salt}").encode("utf-8")
    seed = int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")
    generator = np.random.default_rng(seed)
    
    return float(generator.normal())


@dataclass(frozen=True)
class MetJet:

    raw_pt: float
    eta: float
    phi: float
    area: float
    muon_subtr_factor: float
    ch_em_fraction: float
    ne_em_fraction: float
    source: str
    source_index: int
    gen_index: Optional[int] = None

    @property
    def raw_pt_muon_subtracted(self) -> float:
        return self.raw_pt * (1.0 - self.muon_subtr_factor)

    @property
    def em_fraction(self) -> float:
        return (self.ch_em_fraction+ self.ne_em_fraction)


class JERCProducer(Module):
    def __init__(self, input_file: str, year: str, is_data: bool, jes_sources: Iterable[str] = ("Total",)):
        self.input_file = input_file
        self.year = str(year)
        self.is_data = bool(is_data)
        self.jes_sources = tuple(jes_sources)

        self.campaign: Optional[str] = None
        self.data_era = None
        self._refs: Dict[str, dict] = {}

    def beginJob(self):
        if self.is_data:
            self.data_era = infer_data_era(input_file=self.input_file, requested_year=self.year)
            self.campaign = self.data_era.campaign

            print(f"Data era inferred from filename: Run {self.data_era.year} {self.data_era.run_era} campaign={self.campaign}")
        else:
            self.campaign = campaign_for_mc(year=self.year, input_file=self.input_file)
            print(f"MC campaign inferred as {self.campaign}")

        for kind in ("AK4", "AK8"):
            entry = get_campaign_config(kind=kind, campaign=self.campaign)
            jerc_path = resolve_jerc_json(configured_path=entry["jercJsonPath"], year=self.year, kind=kind)
            print(f"Loading {kind} corrections from {jerc_path}")
            correction_set = (correctionlib.CorrectionSet.from_file(jerc_path))

            if self.is_data:
                config_era = (f"Era{self.campaign}All")
                era_cfg = (entry["ApplyOnData"]["JesNominal"][config_era])
                self._refs[kind] = {
                    "cset": correction_set,
                    "l1": correction_set[era_cfg["tagNameL1FastJet"]],
                    "l2": correction_set[era_cfg["tagNameL2Relative"]],
                    "residual": correction_set[era_cfg["tagNameL2L3Residual"]],
                }
            else:
                mc_cfg = entry["ApplyOnMC"]
                jes_cfg = mc_cfg["JesNominal"]
                jer_cfg = mc_cfg["JerNominal"]

                total_uncertainty_cfg = (mc_cfg["JesUncertaintySet"]["JesUncertaintySetTotal"])
                total_tag = next(iter(total_uncertainty_cfg.values()))
                tags_to_check = {
                    "L1FastJet": jes_cfg["tagNameL1FastJet"],
                    "L2Relative": jes_cfg["tagNameL2Relative"],
                    "PtResolution": jer_cfg["tagNamePtResolution"],
                    "ScaleFactor": jer_cfg["tagNameJerScaleFactor"],
                    "SFUncertainty": jer_cfg.get("tagNameJerSFUncertainty"),
                    "JESTotal": total_tag,
                }


                total_tag = next(iter(total_uncertainty_cfg.values()))
                available_tags = set(correction_set.keys())

                for label, tag in tags_to_check.items():
                    if tag is None:
                        print(f"{label:15s} = None")
                    else:
                        print(f"{label:15s} = {tag} | exists = {tag in available_tags}")

                refs = {
                    "cset": correction_set,
                    "l1": correction_set[jes_cfg["tagNameL1FastJet"]],
                    "l2": correction_set[jes_cfg["tagNameL2Relative"]],
                    "resolution": correction_set[jer_cfg["tagNamePtResolution"]],
                    "sf": correction_set[jer_cfg["tagNameJerScaleFactor"]],
                    "jesTotal": correction_set[total_tag],
                }

                sf_uncertainty_tag = jer_cfg.get("tagNameJerSFUncertainty")

                refs["sf_uncertainty"] = (correction_set[sf_uncertainty_tag] if sf_uncertainty_tag else None)
                self._refs[kind] = refs

    def beginFile(self, inputFile, outputFile, inputTree, wrappedOutputTree):
        self.out = wrappedOutputTree

        for prefix in ("Jet", "FatJet"):
            length_branch = ("nJet" if prefix == "Jet" else "nFatJet")
            for variable in ("pt", "mass"):
                self.out.branch(f"{prefix}_{variable}_nom", "F", lenVar=length_branch)
                
                if not self.is_data:
                    for variation in MC_VARIATIONS:
                        self.out.branch(f"{prefix}_{variable}_{variation}", "F", lenVar=length_branch)

        self.out.branch("PuppiMET_pt_nom", "F")
        self.out.branch("PuppiMET_phi_nom", "F")

        if not self.is_data:
            for variation in MC_VARIATIONS:
                self.out.branch(f"PuppiMET_pt_{variation}", "F")
                self.out.branch(f"PuppiMET_phi_{variation}", "F")

    def _jes_from_raw(self, *, raw_pt: float, raw_mass: float, eta: float, phi: float, area: float, rho: float, run: float, kind: str,
    ) -> Tuple[float, float, float]:
        refs = self._refs[kind]

        values = {
            "area": area,
            "eta": eta,
            "phi": phi,
            "pt": raw_pt,
            "rho": rho,
            "run": float(run),
        }

        l1_factor = float( _evaluate(refs["l1"], values))
        pt_after_l1 = (raw_pt * l1_factor)
        values["pt"] = pt_after_l1

        l2_factor = float(_evaluate(refs["l2"], values))
        total_factor = (l1_factor * l2_factor)

        if self.is_data:
            values["pt"] = (raw_pt * total_factor)

            residual_factor = float(_evaluate(refs["residual"], values))
            total_factor *= residual_factor

        corrected_pt = (raw_pt * total_factor)
        corrected_mass = (raw_mass * total_factor)

        return (corrected_pt, corrected_mass, pt_after_l1)

    def _jes_total_uncertainty(self, kind: str, eta: float, pt: float) -> float:
        return float(_evaluate(self._refs[kind]["jesTotal"],
                {
                    "eta": eta,
                    "pt": pt,
                },
            )
        )

    def _jer_scale_factor(self, *, kind: str, eta: float, pt: float, variation: str) -> float:
        refs = self._refs[kind]

        values = {
            "eta": eta,
            "pt": pt,
        }

        sf_inputs = _correction_inputs(refs["sf"])

        has_string_input = any(input_type == "string" for _, input_type in sf_inputs)

        if refs.get("sf_uncertainty") is None:
            if not has_string_input:
                if variation != "nom":
                    raise RuntimeError(
                        f"JER SF correction "
                        f"'{refs['sf'].name}' has no variation "
                        "input and no separate uncertainty node."
                    )

                return float(_evaluate(refs["sf"], values))

            return float(_evaluate(refs["sf"],{**values, "systematic": variation}))

        nominal_sf = float(_evaluate(refs["sf"],{**values, "systematic": "nom"} if has_string_input else values))

        fractional_uncertainty = float(_evaluate(refs["sf_uncertainty"], values))

        if variation == "up":
            return nominal_sf * (1.0 + fractional_uncertainty)

        if variation == "down":
            return nominal_sf * (1.0 - fractional_uncertainty)

        if variation == "nom":
            return nominal_sf

        raise ValueError(f"Unsupported JER variation: {variation}")

    @staticmethod
    def _find_nearest_gen_jet(*, event, collection_name: str, eta: float, phi: float, maximum_delta_r: float):
        gen_jets = Collection(
            event,
            collection_name,
        )

        nearest = None
        nearest_delta_r = maximum_delta_r

        for gen_jet in gen_jets:
            delta_eta = (eta - gen_jet.eta)
            delta_phi = _wrap_phi(phi - gen_jet.phi)
            delta_r = math.hypot(delta_eta, delta_phi)

            if delta_r < nearest_delta_r:
                nearest = gen_jet
                nearest_delta_r = delta_r

        return nearest

    def _jer_factor(self, *, kind: str, pt: float, eta: float, phi: float, rho: float, event, random_index: int, random_salt: str,variation: str, gen_index: Optional[int] = None, allow_nearest_gen_match: bool = False) -> float:
        refs = self._refs[kind]
        resolution = float(_evaluate(refs["resolution"],{"eta": eta, "pt": pt, "rho": rho}))
        scale_factor = self._jer_scale_factor(kind=kind, eta=eta, pt=pt, variation=variation)

        gen_jet = None

        gen_collection_name = ("GenJet" if kind == "AK4" else "GenJetAK8")
        maximum_delta_r = (0.2 if kind == "AK4" else 0.4)

        if gen_index is not None:
            gen_jets = Collection(event, gen_collection_name)

            if 0 <= gen_index < len(gen_jets):
                gen_jet = gen_jets[gen_index]

        elif allow_nearest_gen_match:
            gen_jet = self._find_nearest_gen_jet(event=event, collection_name=gen_collection_name, eta=eta, phi=phi,maximum_delta_r=maximum_delta_r)

        if gen_jet is not None:
            delta_eta = (eta - gen_jet.eta)
            delta_phi = _wrap_phi(phi - gen_jet.phi)
            delta_r = math.hypot(delta_eta, delta_phi)

            matches_resolution = (abs(pt - gen_jet.pt) < 3.0 * resolution * pt)

            if (delta_r < maximum_delta_r and matches_resolution):
                hybrid_factor = (1.0 + (scale_factor - 1.0)* (pt - gen_jet.pt)/ pt)

                return max(0.0, hybrid_factor)

        stochastic_width = (resolution* math.sqrt(max(scale_factor * scale_factor - 1.0, 0.0)))

        random_number = _stable_gaussian(run=event.run, lumi=event.luminosityBlock, event=event.event, index=random_index,salt=random_salt)

        stochastic_factor = (1.0 + random_number* stochastic_width)

        return max(0.0, stochastic_factor)

    def _smear_pt(self, *, kind: str, pt: float, eta: float, phi: float, rho: float, event, random_index: int, random_salt: str,variation: str, gen_index: Optional[int], allow_nearest_gen_match: bool = False) -> float:
        if self.is_data:
            return pt

        factor = self._jer_factor(kind=kind, pt=pt, eta=eta, phi=phi, rho=rho, event=event, random_index=random_index, random_salt=random_salt, variation=variation, gen_index=gen_index, allow_nearest_gen_match=allow_nearest_gen_match)

        return pt * factor

    def _correct_collection(self, *, event, collection_name: str, kind: str, rho: float):
        jets = Collection(event, collection_name)

        output = {
            key: []
            for key in ("pt_nom", "mass_nom", "pt_jesTotalUp", "mass_jesTotalUp", "pt_jesTotalDown", "mass_jesTotalDown", "pt_jerUp", "mass_jerUp", "pt_jerDown", "mass_jerDown")}

        for jet_index, jet in enumerate(jets):
            raw_pt = (jet.pt* (1.0 - jet.rawFactor))
            raw_mass = (jet.mass* (1.0 - jet.rawFactor))

            jec_pt, jec_mass, _ = (self._jes_from_raw(raw_pt=raw_pt, raw_mass=raw_mass, eta=jet.eta, phi=jet.phi, area=jet.area,rho=rho, run=event.run, kind=kind))

            if self.is_data:
                output["pt_nom"].append(jec_pt)
                output["mass_nom"].append(jec_mass)
                continue

            gen_index_name = ("genJetIdx" if kind == "AK4" else "genJetAK8Idx")

            gen_index = getattr(jet, gen_index_name, -1)

            nominal_pt = self._smear_pt(kind=kind, pt=jec_pt, eta=jet.eta, phi=jet.phi, rho=rho, event=event, random_index=jet_index, random_salt=kind, variation="nom", gen_index=gen_index)

            nominal_scale = (nominal_pt / jec_pt if jec_pt > 0.0 else 1.0)

            output["pt_nom"].append(nominal_pt)
            output["mass_nom"].append(jec_mass * nominal_scale)

            total_uncertainty = (self._jes_total_uncertainty(kind=kind, eta=jet.eta, pt=jec_pt))

            for direction, sign in (("Up", +1.0), ("Down", -1.0)):
                shifted_jec_pt = (jec_pt* (1.0+ sign * total_uncertainty))
                shifted_jec_mass = (jec_mass* (1.0+ sign * total_uncertainty))

                shifted_final_pt = (self._smear_pt(kind=kind, pt=shifted_jec_pt, eta=jet.eta, phi=jet.phi, rho=rho, event=event,
                        random_index=jet_index, random_salt=kind, variation="nom", gen_index=gen_index))

                shifted_jer_scale = (shifted_final_pt/ shifted_jec_pt if shifted_jec_pt > 0.0 else 1.0)

                output[f"pt_jesTotal{direction}"].append(shifted_final_pt)
                output[f"mass_jesTotal{direction}"].append(shifted_jec_mass* shifted_jer_scale)

            for direction, jer_variation in (("Up", "up"), ("Down", "down")):
                shifted_final_pt = (self._smear_pt(kind=kind, pt=jec_pt, eta=jet.eta, phi=jet.phi, rho=rho, event=event, random_index=jet_index, random_salt=kind, variation=jer_variation, gen_index=gen_index))

                shifted_scale = (shifted_final_pt / jec_pt if jec_pt > 0.0 else 1.0)

                output[f"pt_jer{direction}"].append(shifted_final_pt)

                output[f"mass_jer{direction}"].append(jec_mass * shifted_scale)

        return jets, output

    def _build_met_jets(self, event) -> list[MetJet]:
        
        met_jets: list[MetJet] = []

        corr_t1_met_jets = Collection(event, "CorrT1METJet")

        for index, jet in enumerate(corr_t1_met_jets):
            met_jets.append(MetJet(raw_pt=float(jet.rawPt), eta=float(jet.eta), phi=float(jet.phi), area=float(jet.area), muon_subtr_factor=float(getattr(jet, "muonSubtrFactor", 0.0)), ch_em_fraction=0.0, ne_em_fraction=0.0, source="CorrT1METJet", source_index=index, gen_index=None))

        standard_jets = Collection(event,"Jet")

        for index, jet in enumerate(standard_jets):
            raw_pt = (jet.pt* (1.0 - jet.rawFactor))
            if self.is_data:
                gen_index = None
            else:
                gen_index = int(jet.genJetIdx)

            met_jets.append(MetJet(raw_pt=float(raw_pt), eta=float(jet.eta), phi=float(jet.phi), 
                    area=float(jet.area), muon_subtr_factor=float(getattr(jet, "muonSubtrFactor", 0.0)),
                    ch_em_fraction=float(getattr(jet, "chEmEF", 0.0)),
                    ne_em_fraction=float(getattr(jet,"neEmEF", 0.0)),
                    source="Jet",
                    source_index=index,
                    gen_index=gen_index))

        return met_jets

    def _correct_met_jet_pt(self, *, met_jet: MetJet, event, rho: float, variation: str, combined_index: int) -> Tuple[float, float]:
        raw_pt_muon_subtracted = (met_jet.raw_pt_muon_subtracted)

        jec_pt, _, pt_l1 = (self._jes_from_raw(raw_pt=raw_pt_muon_subtracted, raw_mass=0.0, eta=met_jet.eta, phi=met_jet.phi,area=met_jet.area, rho=rho, run=event.run, kind="AK4"))

        if self.is_data:
            return pt_l1, jec_pt

        jer_variation = "nom"

        if variation in ("jesTotalUp", "jesTotalDown"):
            sign = (+1.0 if variation.endswith("Up") else -1.0)
            uncertainty = (self._jes_total_uncertainty(kind="AK4", eta=met_jet.eta, pt=jec_pt))
            jec_pt *= (1.0+ sign * uncertainty)

        elif variation == "jerUp":
            jer_variation = "up"

        elif variation == "jerDown":
            jer_variation = "down"

        elif variation != "nom":
            raise ValueError(f"Unsupported MET variation: {variation}")

        final_pt = self._smear_pt(kind="AK4", pt=jec_pt, eta=met_jet.eta, phi=met_jet.phi, rho=rho, event=event, random_index=combined_index, random_salt=(f"MET:{met_jet.source}"), variation=jer_variation, gen_index=met_jet.gen_index,allow_nearest_gen_match=(met_jet.source == "CorrT1METJet"))

        return pt_l1, final_pt

    def _type1_puppimet(
        self,
        *,
        event,
        rho: float,
        variation: str,
    ) -> Tuple[float, float]:
        """
        Recompute one Type-1 PuppiMET nominal/systematic variation.

        The calculation starts from RawPuppiMET. Both CorrT1METJet and
        standard Jet objects contribute to the Type-1 correction.
        """

        raw_puppimet = Object(event,"RawPuppiMET")
        met_px = (raw_puppimet.pt* math.cos(raw_puppimet.phi))
        met_py = (raw_puppimet.pt* math.sin(raw_puppimet.phi))
        met_jets = self._build_met_jets(event)

        for combined_index, met_jet in enumerate(met_jets):
            pt_l1, final_pt = (self._correct_met_jet_pt(met_jet=met_jet, event=event, rho=rho, variation=variation, combined_index=combined_index))

            passes_type1 = (final_pt > 15.0 and abs(met_jet.eta) < 5.2 and met_jet.em_fraction < 0.9)
            if not passes_type1:
                continue

            delta_pt = (final_pt - pt_l1)
            met_px -= (delta_pt* math.cos(met_jet.phi))
            met_py -= (delta_pt* math.sin(met_jet.phi))

        corrected_met_pt = math.hypot(met_px, met_py)
        corrected_met_phi = math.atan2(met_py, met_px)

        return (corrected_met_pt, corrected_met_phi)

    def analyze(self, event):
        rho = float(event.Rho_fixedGridRhoFastjetAll)

        _, ak4_values = (self._correct_collection(event=event, collection_name="Jet", kind="AK4", rho=rho))
        _, ak8_values = (self._correct_collection(event=event, collection_name="FatJet", kind="AK8", rho=rho))

        for prefix, values in (("Jet", ak4_values), ("FatJet", ak8_values)):
            self.out.fillBranch(f"{prefix}_pt_nom",values["pt_nom"])
            self.out.fillBranch(f"{prefix}_mass_nom", values["mass_nom"])

            if not self.is_data:
                for variation in MC_VARIATIONS:
                    self.out.fillBranch(f"{prefix}_pt_{variation}", values[f"pt_{variation}"])
                    self.out.fillBranch(f"{prefix}_mass_{variation}", values[f"mass_{variation}"])

        nominal_met_pt, nominal_met_phi = (self._type1_puppimet(event=event, rho=rho, variation="nom"))

        self.out.fillBranch("PuppiMET_pt_nom", nominal_met_pt)
        self.out.fillBranch("PuppiMET_phi_nom",nominal_met_phi)

        if not self.is_data:
            for variation in MC_VARIATIONS:
                varied_met_pt, varied_met_phi = (
                    self._type1_puppimet(event=event, rho=rho, variation=variation))

                self.out.fillBranch(f"PuppiMET_pt_{variation}", varied_met_pt)
                self.out.fillBranch(f"PuppiMET_phi_{variation}", varied_met_phi)
        return True