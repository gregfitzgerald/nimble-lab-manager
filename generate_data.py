#!/usr/bin/env python3
"""Parameterized synthetic-data generator for Nimble Lab Manager.

Fabricates a self-consistent lab "world" into a fresh SQLite database so the
map, analytics, forecast, and alerts endpoints all light up with realistic
signal -- and so the schema is shown to scale well beyond the hand-written
seed.sql.

Stdlib only. Fully reproducible: everything random flows through a single
random.Random(seed); all relative dates are anchored to a fixed "today"
(default 2026-07-04, override with --today) so expiring / expired / low-stock
cases are guaranteed to appear regardless of the wall clock.

    python3 generate_data.py --preset chaotic --seed 7 --db lab.db --force

The generated DB is loginable with the four demo accounts (admin/manager/
member/viewer) because auth.ensure_demo_users() is invoked on it.

Hard invariant, asserted at the end: for every inventory item,
    quantity_on_hand == SUM(item_lot.quantity)
"""

import argparse
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta

# Curated real molecular-biology products + real chemical identities (POC).
from molbio_catalog import MOLBIO_CATALOG, REAL_CHEMICALS

# --------------------------------------------------------------------------- #
# presets
# --------------------------------------------------------------------------- #
# rooms = number of *lab* rooms (a vivarium room is always added on top).
# chaos in [0,1] scales the fraction of expired lots, stockouts, misplaced
# vials, and overdue protocols/training.
PRESETS = {
    "small": dict(
        rooms=1, freezers=1, boxes_per_freezer=2, items=15, days=120,
        staff=5, protocols=3, animals=9, chaos=0.15,
    ),
    "core": dict(
        rooms=2, freezers=3, boxes_per_freezer=3, items=120, days=365,
        staff=8, protocols=5, animals=40, chaos=0.35,
    ),
    "chaotic": dict(
        rooms=3, freezers=3, boxes_per_freezer=4, items=120, days=365,
        staff=9, protocols=6, animals=52, chaos=0.80,
    ),
}

DEFAULT_TODAY = "2026-07-04"

# --------------------------------------------------------------------------- #
# value pools (realistic ranges/style, mirrors seed.sql)
# --------------------------------------------------------------------------- #
STAFF_NAMES = [
    "A. Rivera", "J. Chen", "M. Okafor", "S. Patel", "L. Nguyen",
    "D. Kowalski", "R. Haddad", "T. Yamamoto", "E. Santos", "P. Andersson",
    "K. Mbeki", "F. Rossi",
]

STRAINS = [
    "C57BL/6J", "Sprague-Dawley", "BALB/c", "CNTNAP2-KO", "FVB/N", "129S1/SvImJ",
]

PROTOCOL_TITLES = [
    "Rodent models of cognitive decline",
    "Environmental enrichment behavioral assays",
    "Whole-brain imaging pilot",
    "Chronic stress and hippocampal plasticity",
    "Optogenetic control of feeding circuits",
    "Developmental cortical wiring in knockouts",
    "Sleep deprivation and memory consolidation",
    "Motor learning in aged animals",
]

TRAINING_COURSES = [
    "IACUC Core", "Bloodborne Pathogens", "Rodent Surgery",
    "Biosafety Level 2", "Radiation Safety", "Chemical Hygiene",
]

# category -> (names, vendors, units, (cost_lo, cost_hi), expiry_bearing, boxable)
ITEM_CATEGORIES = {
    "reagent": (
        ["4% Paraformaldehyde", "PBS 10x", "Tris-HCl 1M pH 8.0", "Ethanol 200 proof",
         "Methanol", "DMSO", "Glycerol", "Sucrose", "Triton X-100",
         "Bovine Serum Albumin", "Sodium Azide 10%", "EDTA 0.5M", "HEPES 1M",
         "Sodium Chloride", "Isoflurane", "Ketamine"],
        ["Sigma", "Fisher", "VWR", "Thermo", "VetOne", "Covetrus"],
        ["L", "bottle", "g", "vial"],
        (20.0, 98.0), True, False,
    ),
    "antibody": (
        ["Anti-NeuN antibody", "Anti-GFAP antibody", "Anti-GABA antibody",
         "Anti-Iba1 antibody", "Anti-c-Fos antibody", "Anti-Tuj1 antibody",
         "Anti-MAP2 antibody", "Anti-Parvalbumin antibody", "Anti-Calbindin antibody",
         "Anti-Tyrosine Hydroxylase antibody", "Anti-Ki67 antibody", "Anti-DAPI stain"],
        ["Abcam", "Millipore", "Cell Signaling", "Dako", "Invitrogen"],
        ["vial"],
        (185.0, 445.0), True, True,
    ),
    "media": (
        ["DMEM High Glucose", "Fetal Bovine Serum", "Trypsin-EDTA 0.25%",
         "Penicillin-Streptomycin", "Neurobasal Medium", "B-27 Supplement",
         "L-Glutamine", "Opti-MEM", "RPMI 1640", "HBSS"],
        ["Gibco", "Corning", "Lonza"],
        ["bottle", "vial"],
        (24.0, 220.0), True, True,
    ),
    "enzyme": (
        ["Taq DNA Polymerase", "dNTP Mix 10mM", "T4 DNA Ligase", "Proteinase K",
         "DNase I", "RNase A", "Q5 Polymerase", "EcoRI Restriction Enzyme",
         "Reverse Transcriptase", "Phusion Polymerase"],
        ["NEB", "Promega", "Roche", "Takara"],
        ["vial", "tube"],
        (48.0, 205.0), True, True,
    ),
    "consumable": (
        ["Nitrile gloves M", "Nitrile gloves L", "Pipette tips 200uL",
         "Pipette tips 1000uL", "Microscope slides", "Cover slips",
         "15mL conical tubes", "50mL conical tubes", "Cryovials",
         "PCR plates", "Serological pipettes", "Weigh boats"],
        ["Fisher", "Rainin", "Corning", "Eppendorf", "Kimberly-Clark"],
        ["box", "case", "pack"],
        (10.0, 160.0), False, False,
    ),
}
CATEGORY_ORDER = ["reagent", "antibody", "media", "enzyme", "consumable"]

# The generator's internal buckets above are mapped onto the inventory.category
# values the schema documents (reagent, supply, chemical, antibody, enzyme,
# media, animal, equipment, other). "consumable" -> "supply"; a handful of wet
# reagents are really hazardous chemicals -> "chemical".
CHEMICAL_NAMES = {
    "Isoflurane", "Ketamine", "Ethanol 200 proof", "Methanol", "DMSO",
    "Sodium Azide 10%", "Triton X-100",
}
# categories that carry a product-level Safety Data Sheet
SDS_CATEGORIES = {"chemical", "reagent", "antibody", "enzyme"}
# categories whose lots plausibly ship with a Certificate of Analysis
COA_CATEGORIES = {"chemical", "reagent", "antibody", "enzyme", "media"}
# categories whose SDS carries a disposal (section 13) instruction we surface on
# the item. Plain supplies and media stay NULL.
DISPOSAL_BY_CATEGORY = {
    "chemical":  "See SDS section 13. Hazardous chemical waste -- collect in a "
                 "sealed, labeled container; do not pour down the drain.",
    "reagent":   "See SDS section 13. Neutralize/dilute and dispose per local "
                 "hazardous-waste rules; do not pour down the drain.",
    "antibody":  "Antibody in sodium-azide preservative -- dispose as hazardous "
                 "waste per SDS section 13; azide reacts with plumbing metals.",
}

# DEA-scheduled controlled substances that may appear in the reagent pool. Maps
# an item's base name to its schedule string. Ketamine is the common one; the
# others are included so a matching generated item lands on the register.
CONTROLLED_SCHEDULES = {
    "Ketamine": "III", "Pentobarbital": "II", "Fentanyl": "II",
    "Diazepam": "IV", "Midazolam": "IV",
}
# Reasons booked against a controlled-substance dispense.
CONTROLLED_REASONS = [
    "Rodent survival surgery", "Terminal perfusion", "Sedation for imaging",
    "Euthanasia", "Analgesia dosing",
]

# Recurring bench procedures seeded as task_templates. Each line is
# (category_pool, default_quantity); the generator resolves the pool to a real
# generated item of that category (falling back to any item if absent).
TEMPLATE_SPECS = [
    ("Perfusion", "Transcardial perfusion + fixation of rodents.",
     [("chemical", 1), ("chemical", 1), ("reagent", 2), ("reagent", 1)]),
    ("Western Blot", "SDS-PAGE immunoblot for a target protein.",
     [("antibody", 1), ("reagent", 1), ("reagent", 1)]),
    ("Immunostaining", "Fluorescent immunohistochemistry on fixed sections.",
     [("antibody", 1), ("reagent", 1), ("chemical", 1)]),
    ("Genotyping PCR", "Endpoint PCR genotyping of tail/ear samples.",
     [("enzyme", 1), ("enzyme", 2), ("reagent", 1)]),
]


# --------------------------------------------------------------------------- #
# Wave 2 pools: bundled vendor catalog, substitute groups, chemical-safety
# metadata. The catalog is a FIXED set of real products (real catalog numbers,
# pack sizes, list prices, manufacturer SDS/product URL patterns); it is emitted
# verbatim so its row counts are identical for every seed. Generated inventory
# items are linked to a catalog row when their base name matches CATALOG_LINK,
# and chemical items are enriched with a GHS hazard class + CAS number from the
# maps below. Mirrors the vendor_catalog / substitute_group data in seed.sql.
# --------------------------------------------------------------------------- #
def _thermo_sds(cat):
    return ("https://www.thermofisher.com/document-connect/document-connect.html?"
            "url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F"
            f"{cat}_SDS.pdf")


def _thermo_prod(cat):
    return f"https://www.thermofisher.com/order/catalog/product/{cat}"


def _sigma_sds(brand, cat):
    return f"https://www.sigmaaldrich.com/US/en/sds/{brand}/{cat.lower()}"


def _sigma_prod(brand, cat):
    return f"https://www.sigmaaldrich.com/US/en/product/{brand}/{cat.lower()}"


SUBSTITUTE_GROUP_ROWS = [
    (1, "Paraformaldehyde, powder", "chemical",
     "Reagent-grade paraformaldehyde powder for fresh fixative; "
     "interchangeable across suppliers."),
    (2, "DMEM, high glucose", "media",
     "High-glucose Dulbecco's Modified Eagle Medium, 500 mL bottles."),
    (3, "Taq DNA polymerase", "enzyme",
     "Standard thermostable Taq polymerase for endpoint genotyping PCR."),
    (4, "Trypsin-EDTA 0.25%", "reagent",
     "0.25% trypsin-EDTA with phenol red for adherent-cell passaging."),
]

# (id, vendor, catalog_number, product_name, category, pack_size, unit,
#  list_price, sds_url, product_url, cas_number, hazard_class,
#  substitute_group_id, preference_rank, availability). Groups 1 and 3 have their
#  rank-1 member on backorder so the "preferred in stock" fall-through resolves
#  to the rank-2 member.
VENDOR_CATALOG_ROWS = [
    (1, "Sigma-Aldrich", "P6148", "Paraformaldehyde, reagent grade, powder", "chemical", "500 g", "g", 138.00, _sigma_sds("sigma", "P6148"), _sigma_prod("sigma", "P6148"), "30525-89-4", "toxic,irritant", 1, 1, "backorder"),
    (2, "Electron Microscopy Sciences", "19200", "Paraformaldehyde, granular, EM grade", "chemical", "500 g", "g", 96.50, "https://www.emsdiasum.com/sds/19200", "https://www.emsdiasum.com/paraformaldehyde-granular", "30525-89-4", "toxic,irritant", 1, 2, "in_stock"),
    (3, "Thermo Scientific", "A11313", "Paraformaldehyde, 96%", "chemical", "500 g", "g", 84.00, _thermo_sds("A11313"), _thermo_prod("A11313"), "30525-89-4", "toxic,irritant", 1, 3, "in_stock"),
    (4, "Gibco", "11965092", "DMEM, high glucose, pyruvate", "media", "500 mL", "bottle", 24.30, _thermo_sds("11965092"), _thermo_prod("11965092"), None, None, 2, 1, "in_stock"),
    (5, "Corning", "10-013-CV", "DMEM, high glucose with L-glutamine", "media", "500 mL", "bottle", 21.75, "https://ecatalog.corning.com/life-sciences/b2b/US/en/sds/10-013-CV", "https://ecatalog.corning.com/life-sciences/b2b/US/en/Cell-Culture/Media/10-013-CV", None, None, 2, 2, "in_stock"),
    (6, "Sigma-Aldrich", "D5796", "DMEM, high glucose", "media", "500 mL", "bottle", 28.40, _sigma_sds("sigma", "D5796"), _sigma_prod("sigma", "D5796"), None, None, 2, 3, "backorder"),
    (7, "NEB", "M0273", "Taq DNA Polymerase with Standard Taq Buffer", "enzyme", "2000 units", "vial", 145.00, "https://www.neb.com/-/media/nebus/files/sds/m0273_sds.pdf", "https://www.neb.com/en-us/products/m0273-taq-dna-polymerase-with-standard-taq-buffer", None, None, 3, 1, "backorder"),
    (8, "Invitrogen", "10342020", "Platinum Taq DNA Polymerase", "enzyme", "500 units", "vial", 168.00, _thermo_sds("10342020"), _thermo_prod("10342020"), None, None, 3, 2, "in_stock"),
    (9, "Promega", "M3001", "GoTaq DNA Polymerase", "enzyme", "500 units", "vial", 132.00, "https://www.promega.com/-/media/files/resources/sds/m300/m3001.pdf", "https://www.promega.com/products/pcr/taq-polymerase/gotaq-dna-polymerase/", None, None, 3, 3, "in_stock"),
    (10, "Gibco", "25200056", "Trypsin-EDTA (0.25%), phenol red", "reagent", "100 mL", "bottle", 31.20, _thermo_sds("25200056"), _thermo_prod("25200056"), None, "irritant", 4, 1, "in_stock"),
    (11, "Corning", "25-053-CI", "Trypsin-EDTA 0.25%", "reagent", "100 mL", "bottle", 27.80, "https://ecatalog.corning.com/life-sciences/b2b/US/en/sds/25-053-CI", "https://ecatalog.corning.com/life-sciences/b2b/US/en/Cell-Culture/25-053-CI", None, "irritant", 4, 2, "in_stock"),
    (12, "Gibco", "16000044", "Fetal Bovine Serum, qualified, US origin", "media", "500 mL", "bottle", 685.00, _thermo_sds("16000044"), _thermo_prod("16000044"), None, None, None, None, "in_stock"),
    (13, "Sigma-Aldrich", "F2442", "Fetal Bovine Serum", "media", "500 mL", "bottle", 549.00, _sigma_sds("sigma", "F2442"), _sigma_prod("sigma", "F2442"), None, None, None, None, "in_stock"),
    (14, "Gibco", "15140122", "Penicillin-Streptomycin (10,000 U/mL)", "media", "100 mL", "bottle", 28.60, _thermo_sds("15140122"), _thermo_prod("15140122"), None, None, None, None, "in_stock"),
    (15, "NEB", "N0447", "Deoxynucleotide (dNTP) Solution Mix, 10 mM", "reagent", "8 umol", "tube", 62.00, "https://www.neb.com/-/media/nebus/files/sds/n0447_sds.pdf", "https://www.neb.com/en-us/products/n0447-deoxynucleotide-dntp-solution-mix", None, None, None, None, "in_stock"),
    (16, "Gibco", "70011044", "PBS (10X), pH 7.4", "reagent", "1 L", "bottle", 41.50, _thermo_sds("70011044"), _thermo_prod("70011044"), None, None, None, None, "in_stock"),
    (17, "Invitrogen", "15568025", "Tris-HCl (1 M), pH 8.0", "reagent", "1 L", "bottle", 58.00, _thermo_sds("15568025"), _thermo_prod("15568025"), "1185-53-1", None, None, None, "in_stock"),
    (18, "Bio-Rad", "1613101", "Certified Molecular Biology Agarose", "reagent", "500 g", "box", 289.00, "https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1613101.pdf", "https://www.bio-rad.com/en-us/sku/1613101-certified-molecular-biology-agarose", "9012-36-6", None, None, None, "in_stock"),
    (19, "Invitrogen", "16500500", "UltraPure Agarose", "reagent", "500 g", "box", 245.00, _thermo_sds("16500500"), _thermo_prod("16500500"), "9012-36-6", None, None, None, "in_stock"),
    (20, "Millipore Sigma", "MAB377", "Anti-NeuN Antibody, clone A60", "antibody", "100 uL", "vial", 469.00, _sigma_sds("mm", "MAB377"), _sigma_prod("mm", "MAB377"), None, None, None, None, "in_stock"),
    (21, "Abcam", "ab177487", "Anti-NeuN antibody [EPR12763]", "antibody", "100 uL", "vial", 425.00, "https://www.abcam.com/en-us/products/primary-antibodies/neun-antibody-epr12763-ab177487#support-msds", "https://www.abcam.com/en-us/products/primary-antibodies/neun-antibody-epr12763-ab177487", None, None, None, None, "in_stock"),
    (22, "Agilent (Dako)", "Z0334", "Polyclonal Rabbit Anti-GFAP", "antibody", "10 mL", "vial", 312.00, "https://www.agilent.com/store/en_US/Prod-Z033429-2/Z0334", "https://www.agilent.com/store/en_US/Prod-Z033429-2/Z0334", None, None, None, None, "in_stock"),
    (23, "Cell Signaling Technology", "12389", "GFAP (D1F4Q) XP Rabbit mAb", "antibody", "100 uL", "vial", 389.00, "https://www.cellsignal.com/products/primary-antibodies/gfap-d1f4q-xp-rabbit-mab/12389#product-support", "https://www.cellsignal.com/products/primary-antibodies/gfap-d1f4q-xp-rabbit-mab/12389", None, None, None, None, "in_stock"),
    (24, "Sigma-Aldrich", "D2650", "Dimethyl sulfoxide (DMSO), Hybri-Max, sterile", "chemical", "100 mL", "bottle", 72.00, _sigma_sds("sigma", "D2650"), _sigma_prod("sigma", "D2650"), "67-68-5", "irritant", None, None, "in_stock"),
    (25, "Sigma-Aldrich", "X100", "Triton X-100", "chemical", "500 mL", "bottle", 68.50, _sigma_sds("sigma", "X100"), _sigma_prod("sigma", "X100"), "9002-93-1", "corrosive,irritant", None, None, "in_stock"),
    (26, "Sigma-Aldrich", "E7023", "Ethanol, 200 proof, anhydrous", "chemical", "1 L", "bottle", 96.00, _sigma_sds("sigma", "E7023"), _sigma_prod("sigma", "E7023"), "64-17-5", "flammable,irritant", None, None, "in_stock"),
    (27, "Sigma-Aldrich", "179337", "Methanol, anhydrous 99.8%", "chemical", "1 L", "bottle", 58.00, _sigma_sds("sial", "179337"), _sigma_prod("sial", "179337"), "67-56-1", "flammable,toxic", None, None, "in_stock"),
    (28, "Electron Microscopy Sciences", "16000", "Glutaraldehyde, 25% EM grade", "chemical", "10 x 10 mL", "ampule", 44.00, "https://www.emsdiasum.com/sds/16000", "https://www.emsdiasum.com/glutaraldehyde-25", "111-30-8", "toxic,corrosive", None, None, "in_stock"),
    (29, "Sigma-Aldrich", "A9647", "Bovine Serum Albumin, lyophilized", "reagent", "100 g", "bottle", 168.00, _sigma_sds("sigma", "A9647"), _sigma_prod("sigma", "A9647"), "9048-46-8", None, None, None, "in_stock"),
    (30, "Bio-Rad", "1610747", "4x Laemmli Sample Buffer", "reagent", "10 mL", "bottle", 96.00, "https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1610747.pdf", "https://www.bio-rad.com/en-us/sku/1610747-4x-laemmli-sample-buffer", None, "flammable,irritant", None, None, "in_stock"),
    (31, "Sigma-Aldrich", "A0280", "Anti-GABA antibody", "antibody", "200 uL", "vial", 388.00, _sigma_sds("sigma", "A0280"), _sigma_prod("sigma", "A0280"), None, None, None, None, "discontinued"),
]

# Generated inventory base name -> vendor_catalog id (soft link).
CATALOG_LINK = {
    "4% Paraformaldehyde": 1, "DMEM High Glucose": 4, "Fetal Bovine Serum": 12,
    "Trypsin-EDTA 0.25%": 10, "Taq DNA Polymerase": 7, "dNTP Mix 10mM": 15,
    "Anti-NeuN antibody": 20, "Anti-GFAP antibody": 22, "PBS 10x": 16,
    "Tris-HCl 1M pH 8.0": 17, "Anti-GABA antibody": 31, "DMSO": 24,
    "Triton X-100": 25, "Ethanol 200 proof": 26, "Methanol": 27,
    "Bovine Serum Albumin": 29,
}
# CAS numbers + GHS hazard classes keyed on generated item base names.
CHEMICAL_CAS = {
    "Isoflurane": "26675-46-7", "Ketamine": "6740-88-1",
    "4% Paraformaldehyde": "30525-89-4", "DMSO": "67-68-5",
    "Triton X-100": "9002-93-1", "Ethanol 200 proof": "64-17-5",
    "Methanol": "67-56-1", "Sodium Azide 10%": "26628-22-8",
    "Tris-HCl 1M pH 8.0": "1185-53-1", "Glycerol": "56-81-5",
}
CHEMICAL_HAZARDS = {
    "Isoflurane": "irritant", "Ketamine": "toxic",
    "4% Paraformaldehyde": "toxic,irritant", "DMSO": "irritant",
    "Triton X-100": "corrosive,irritant", "Ethanol 200 proof": "flammable,irritant",
    "Methanol": "flammable,toxic", "Sodium Azide 10%": "toxic",
    "Tris-HCl 1M pH 8.0": "irritant",
}


# --------------------------------------------------------------------------- #
# Wave 4: procedural bulk-catalog synthesis (--catalog N)
# --------------------------------------------------------------------------- #
# When --catalog N (N > 0) is passed, N extra vendor_catalog rows are synthesized
# on top of the fixed VENDOR_CATALOG_ROWS above (ids continue after the fixed set,
# substitute_group_id / preference_rank left NULL). Everything below is drawn via
# the generator's own seeded rng, so a given --seed reproduces the same catalog.
# Real-vendor catalog-number shapes + SDS/product URLs mirror the hand-written
# rows: where a synthetic vendor has a builder above it is reused, else a
# plausible manufacturer URL is produced.
_DIGITS = "0123456789"


def _digits(rng, n):
    return "".join(rng.choice(_DIGITS) for _ in range(n))


# -- extra manufacturer URL builders (parallel to _thermo_*/_sigma_* above) -- #
def _bio_rad_sds(c):
    return f"https://www.bio-rad.com/webroot/web/pdf/lsr/sds/{c}.pdf"


def _bio_rad_prod(c):
    return f"https://www.bio-rad.com/en-us/sku/{c}"


def _neb_sds(c):
    return f"https://www.neb.com/-/media/nebus/files/sds/{c.lower()}_sds.pdf"


def _neb_prod(c):
    return f"https://www.neb.com/en-us/products/{c.lower()}"


def _abcam_sds(c):
    return f"https://www.abcam.com/en-us/products/{c.lower()}#support-msds"


def _abcam_prod(c):
    return f"https://www.abcam.com/en-us/products/{c.lower()}"


def _cst_sds(c):
    return f"https://www.cellsignal.com/products/{c}#product-support"


def _cst_prod(c):
    return f"https://www.cellsignal.com/products/{c}"


def _corning_sds(c):
    return f"https://ecatalog.corning.com/life-sciences/b2b/US/en/sds/{c}"


def _corning_prod(c):
    return f"https://ecatalog.corning.com/life-sciences/b2b/US/en/product/{c}"


def _qiagen_sds(c):
    return f"https://www.qiagen.com/us/resources/sds/{c}"


def _qiagen_prod(c):
    return f"https://www.qiagen.com/us/products/{c}"


def _generic_url(vendor, kind, c):
    slug = re.sub(r"[^a-z0-9]+", "", vendor.lower())
    return f"https://www.{slug}.com/{kind}/{c}"


def _mk_generic(vendor):
    return (lambda c: _generic_url(vendor, "sds", c),
            lambda c: _generic_url(vendor, "product", c))


# -- vendor catalog-number "shape" functions (rng -> string) ------------------ #
def _cat_sigma(rng):
    if rng.random() < 0.7:
        return rng.choice("ABCDEGHILMPRSTVWXYZ") + _digits(rng, rng.randint(3, 4))
    return _digits(rng, 6)


def _cat_thermo(rng):
    if rng.random() < 0.6:
        return _digits(rng, rng.randint(7, 8))
    return "A" + _digits(rng, 5)


def _cat_neb(rng):
    return rng.choice("MNPRST") + _digits(rng, 4)


def _cat_biorad(rng):
    return _digits(rng, 7)


def _cat_abcam(rng):
    return "ab" + _digits(rng, rng.randint(5, 6))


def _cat_cst(rng):
    return _digits(rng, rng.randint(4, 5))


def _cat_corning(rng):
    return f"{_digits(rng, 2)}-{_digits(rng, 3)}-{rng.choice(['CV', 'CI', 'MR'])}"


def _cat_qiagen(rng):
    return _digits(rng, rng.randint(5, 6))


def _cat_vwr(rng):
    return f"{_digits(rng, 5)}-{_digits(rng, 3)}"


def _cat_roche(rng):
    return _digits(rng, rng.randint(7, 8))


def _cat_promega(rng):
    return rng.choice("AEGMV") + _digits(rng, 4)


def _cat_eppendorf(rng):
    return f"0030 {_digits(rng, 3)}.{_digits(rng, 1)}"


# vendor -> (catalog-number shape fn, sds-url fn, product-url fn)
VENDOR_SPECS = {
    "Thermo Fisher": (_cat_thermo, _thermo_sds, _thermo_prod),
    "Gibco": (_cat_thermo, _thermo_sds, _thermo_prod),
    "Invitrogen": (_cat_thermo, _thermo_sds, _thermo_prod),
    "Sigma-Aldrich": (_cat_sigma, lambda c: _sigma_sds("sigma", c),
                      lambda c: _sigma_prod("sigma", c)),
    "Millipore Sigma": (_cat_sigma, lambda c: _sigma_sds("mm", c),
                        lambda c: _sigma_prod("mm", c)),
    "NEB": (_cat_neb, _neb_sds, _neb_prod),
    "Bio-Rad": (_cat_biorad, _bio_rad_sds, _bio_rad_prod),
    "Abcam": (_cat_abcam, _abcam_sds, _abcam_prod),
    "Cell Signaling Technology": (_cat_cst, _cst_sds, _cst_prod),
    "Corning": (_cat_corning, _corning_sds, _corning_prod),
    "Qiagen": (_cat_qiagen, _qiagen_sds, _qiagen_prod),
    "VWR": (_cat_vwr, *_mk_generic("VWR")),
    "Roche": (_cat_roche, *_mk_generic("Roche")),
    "Promega": (_cat_promega, *_mk_generic("Promega")),
    "Eppendorf": (_cat_eppendorf, *_mk_generic("Eppendorf")),
}

# schema category -> vendors that plausibly sell that category
CATALOG_CATEGORY_VENDORS = {
    "chemical": ["Sigma-Aldrich", "Thermo Fisher", "VWR", "Millipore Sigma"],
    "reagent": ["Sigma-Aldrich", "Thermo Fisher", "Bio-Rad", "Qiagen", "VWR",
                "Promega"],
    "antibody": ["Abcam", "Cell Signaling Technology", "Millipore Sigma",
                 "Invitrogen", "Bio-Rad"],
    "media": ["Gibco", "Corning", "Thermo Fisher"],
    "enzyme": ["NEB", "Promega", "Roche", "Thermo Fisher"],
    "supply": ["VWR", "Corning", "Eppendorf", "Thermo Fisher"],
}
# category draw weights (roughly mirrors a real stockroom's spread)
SYNTH_CATEGORY_POOL = ["chemical", "reagent", "antibody", "media", "enzyme",
                       "supply"]
SYNTH_CATEGORY_WEIGHTS = [26, 22, 14, 12, 12, 14]

# (base product names, grade/size/format qualifiers) per schema category
SYNTH_PRODUCTS = {
    "chemical": (
        ["Paraformaldehyde", "Sodium chloride", "Sucrose", "Glycerol",
         "Sodium hydroxide", "Hydrochloric acid", "Acetic acid, glacial",
         "Sodium azide", "Potassium chloride", "Magnesium chloride hexahydrate",
         "Formaldehyde solution", "Glutaraldehyde", "Chloroform", "Acetone",
         "2-Propanol", "Xylene", "Sodium dodecyl sulfate", "Ammonium persulfate",
         "TEMED", "Boric acid", "Calcium chloride", "Hydrogen peroxide 30%",
         "Sodium bicarbonate", "Dimethyl sulfoxide", "Ethanol, absolute",
         "Methanol", "Sodium phosphate dibasic", "Potassium phosphate monobasic",
         "Trichloroacetic acid", "Beta-mercaptoethanol"],
        ["ACS reagent, >=99%", "anhydrous", "BioReagent", ">=98%",
         "for molecular biology", "reagent grade", "meets USP specifications",
         "puriss.", "ACS grade"]),
    "reagent": (
        ["PBS, 10X", "Tris-HCl, 1 M pH 8.0", "TAE buffer, 50X", "TBS-T, 10X",
         "Bovine Serum Albumin", "UltraPure Agarose", "4X Laemmli Sample Buffer",
         "Protein Blocking Buffer", "DAPI Solution", "Protease Inhibitor Cocktail",
         "6X DNA Loading Dye", "SYBR Safe DNA Gel Stain", "DTT, 1 M",
         "DNA Extraction Kit", "RNA Isolation Kit", "Gel Extraction Kit",
         "BCA Protein Assay Kit", "Plasmid Miniprep Kit", "EDTA, 0.5 M pH 8.0",
         "HEPES, 1 M pH 7.3", "Nuclease-Free Water", "Ponceau S Solution"],
        ["molecular biology grade", "10X concentrate", "nuclease-free",
         "cell culture tested", "BioReagent", "RNase-free", "endotoxin-tested"]),
    "antibody": (
        ["Anti-NeuN antibody", "Anti-GFAP antibody", "Anti-GABA antibody",
         "Anti-Iba1 antibody", "Anti-c-Fos antibody", "Anti-Tuj1 antibody",
         "Anti-MAP2 antibody", "Anti-Parvalbumin antibody",
         "Anti-Calbindin antibody", "Anti-Tyrosine Hydroxylase antibody",
         "Anti-Ki67 antibody", "Anti-beta-Actin antibody", "Anti-GAPDH antibody",
         "Anti-Vimentin antibody", "Anti-CD68 antibody",
         "Anti-Synaptophysin antibody", "Anti-PSD-95 antibody",
         "Anti-NFL antibody", "Anti-Olig2 antibody", "Anti-Sox2 antibody"],
        ["monoclonal", "polyclonal", "clone A60", "[EPR12763]",
         "Alexa Fluor 488 conjugate", "Alexa Fluor 594 conjugate",
         "HRP conjugate", "ChIP grade", "for IHC/IF"]),
    "media": (
        ["DMEM, high glucose", "Fetal Bovine Serum", "Trypsin-EDTA (0.25%)",
         "Penicillin-Streptomycin", "Neurobasal Medium", "B-27 Supplement",
         "L-Glutamine, 200 mM", "Opti-MEM I", "RPMI 1640", "HBSS", "DPBS",
         "MEM", "Ham's F-12", "GlutaMAX Supplement", "Trypan Blue Solution",
         "Fetal Bovine Serum, heat-inactivated"],
        ["high glucose", "with L-glutamine", "GlutaMAX", "US origin",
         "no phenol red", "with sodium pyruvate", "1X", "reduced serum"]),
    "enzyme": (
        ["Taq DNA Polymerase", "Q5 High-Fidelity DNA Polymerase",
         "Phusion DNA Polymerase", "T4 DNA Ligase", "Proteinase K", "DNase I",
         "RNase A", "EcoRI-HF", "BamHI-HF", "HindIII", "NotI-HF",
         "Reverse Transcriptase", "Antarctic Phosphatase", "Exonuclease I",
         "dNTP Solution Mix, 10 mM", "Lysozyme", "Benzonase Nuclease",
         "Klenow Fragment"],
        ["recombinant", "high-fidelity", "with reaction buffer", "cloned",
         "molecular biology grade", "PCR grade"]),
    "supply": (
        ["Nitrile Examination Gloves, M", "Nitrile Examination Gloves, L",
         "Filter Pipette Tips, 200 uL", "Filter Pipette Tips, 1000 uL",
         "Microscope Slides", "Cover Glass, 22x22 mm", "Conical Tubes, 15 mL",
         "Conical Tubes, 50 mL", "Cryogenic Vials, 2 mL", "PCR Plates, 96-well",
         "Serological Pipettes, 10 mL", "Weigh Boats", "Microcentrifuge Tubes",
         "Petri Dishes, 100 mm", "Cell Culture Flask, T-75",
         "Syringe Filters, 0.22 um", "Kimwipes Delicate Task Wipers",
         "Reagent Reservoirs", "Cell Scrapers", "Parafilm M"],
        ["sterile", "non-sterile", "low-retention", "DNase/RNase-free",
         "aerosol barrier", "tissue-culture treated", "individually wrapped"]),
}

# (pack_size, unit) options per schema category
SYNTH_PACKS = {
    "chemical": [("100 g", "g"), ("500 g", "g"), ("1 kg", "g"), ("25 g", "g"),
                 ("500 mL", "mL"), ("1 L", "L"), ("2.5 L", "L"),
                 ("100 mL", "mL"), ("6 x 1 L", "case")],
    "reagent": [("500 mL", "bottle"), ("1 L", "bottle"), ("100 mL", "bottle"),
                ("10 mL", "bottle"), ("100 g", "g"), ("500 g", "box"),
                ("1 kit", "kit"), ("100 rxn", "kit"), ("50 mL", "tube"),
                ("250 mL", "bottle")],
    "antibody": [("100 uL", "vial"), ("50 uL", "vial"), ("200 uL", "vial"),
                 ("25 uL", "vial"), ("1 mg", "vial"), ("500 ug", "vial"),
                 ("10 mL", "vial")],
    "media": [("500 mL", "bottle"), ("100 mL", "bottle"), ("50 mL", "bottle"),
              ("1 L", "bottle"), ("6 x 500 mL", "case")],
    "enzyme": [("2000 units", "vial"), ("500 units", "vial"),
               ("10000 units", "vial"), ("1000 units", "vial"),
               ("5000 units", "vial"), ("8 umol", "tube"), ("100 rxn", "kit")],
    "supply": [("case of 500", "case"), ("box of 96", "box"),
               ("pack of 10", "pack"), ("1000 tips", "box"),
               ("500 tubes", "bag"), ("case", "case"), ("10 x 96-well", "case")],
}

# (list_price low, high) per schema category
SYNTH_PRICE = {
    "chemical": (18.0, 480.0), "reagent": (25.0, 340.0),
    "antibody": (150.0, 620.0), "media": (20.0, 700.0),
    "enzyme": (55.0, 420.0), "supply": (8.0, 260.0),
}

_HAZARD_KEYWORDS = ["flammable", "oxidizer", "corrosive", "toxic", "irritant",
                    "acid", "base", "water-reactive"]


def _synth_cas(rng):
    """Well-formed (not necessarily registered) CAS number NNN-NN-N."""
    return f"{rng.randint(50, 999999)}-{rng.randint(10, 99)}-{rng.randint(0, 9)}"


def _synth_hazard(rng):
    n = rng.choices([1, 2], weights=[70, 30])[0]
    return ",".join(rng.sample(_HAZARD_KEYWORDS, n))


def schema_category(internal_cat, item_name):
    """Map an internal bucket + name to a schema-allowed inventory.category."""
    if internal_cat == "consumable":
        return "supply"
    if internal_cat == "reagent":
        base = item_name.split(" #")[0]        # drop any " #2" dedup suffix
        return "chemical" if base in CHEMICAL_NAMES else "reagent"
    return internal_cat                          # antibody / media / enzyme


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def iso(d):
    return d.isoformat()


def partition(total, k, rng):
    """Split a non-negative int `total` into k non-negative ints that sum to it."""
    if k <= 1:
        return [total]
    parts = []
    remaining = total
    for _ in range(k - 1):
        x = rng.randint(0, remaining)
        parts.append(x)
        remaining -= x
    parts.append(remaining)
    rng.shuffle(parts)
    return parts


def grid_pack(x, y, w, h, n, pad=8.0):
    """Lay out n non-overlapping rectangles inside (x,y,w,h) on a simple grid."""
    if n <= 0:
        return []
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    cw = w / cols
    ch = h / rows
    rects = []
    for i in range(n):
        r, c = divmod(i, cols)
        rects.append((
            round(x + c * cw + pad, 1),
            round(y + r * ch + pad, 1),
            round(cw - 2 * pad, 1),
            round(ch - 2 * pad, 1),
        ))
    return rects


# --------------------------------------------------------------------------- #
# generator
# --------------------------------------------------------------------------- #
class Generator:
    def __init__(self, conn, rng, cfg, today):
        self.conn = conn
        self.rng = rng
        self.cfg = cfg
        self.today = today  # datetime.date
        self.chaos = cfg["chaos"]

        # id counters / collected references
        self._node_id = 0
        self._lot_id = 0
        self._container_id = 0
        self.nodes = []          # location_node rows (tuples)
        self.boxes = []          # box node ids
        self.cages = []          # cage node names
        self.staff_ids = []
        self.pi_ids = []
        self.items = []          # item metadata dicts
        self.lots = []           # lot dicts

    # ---- date helpers ----------------------------------------------------- #
    def past_date(self, lo, hi):
        return self.today - timedelta(days=self.rng.randint(lo, hi))

    def future_date(self, lo, hi):
        return self.today + timedelta(days=self.rng.randint(lo, hi))

    # ---- staff ------------------------------------------------------------ #
    def gen_staff(self):
        n = self.cfg["staff"]
        roles = ["PI", "Lab Manager"] + \
            [self.rng.choice(["Postdoc", "Technician", "Undergraduate"])
             for _ in range(max(0, n - 2))]
        rows = []
        for i in range(n):
            sid = i + 1
            name = STAFF_NAMES[i % len(STAFF_NAMES)]
            role = roles[i]
            slug = name.lower().replace(".", "").replace(" ", "")
            email = f"{slug}{sid}@example.edu"
            hire = self.past_date(120, 3800)
            rows.append((sid, name, role, email, iso(hire)))
            self.staff_ids.append(sid)
            if role == "PI":
                self.pi_ids.append(sid)
        if not self.pi_ids:            # guarantee at least one PI
            self.pi_ids.append(1)
        self.conn.executemany(
            "INSERT INTO staff (staff_id, full_name, role, email, hire_date) "
            "VALUES (?,?,?,?,?)", rows)

    # ---- floors ----------------------------------------------------------- #
    def gen_floors(self):
        """Seed the single floor every location_node.floor_id (=1) points at.

        image_filename is NULL, so the map renders as an abstract schematic in
        the 0..1000 canvas space that gen_locations lays units out in.
        """
        self.conn.execute(
            "INSERT INTO floor (id, name, image_filename, image_width, "
            "image_height) VALUES (?,?,?,?,?)",
            (1, "Main Floor", None, None, None))

    # ---- location tree ---------------------------------------------------- #
    def _new_node(self, parent_id, kind, name, rows=None, cols=None,
                  floor_id=None, box=None):
        self._node_id += 1
        nid = self._node_id
        mx, my, mw, mh = (box if box else (None, None, None, None))
        self.nodes.append((nid, parent_id, kind, name, rows, cols,
                           floor_id, mx, my, mw, mh))
        return nid

    def gen_locations(self):
        n_lab = self.cfg["rooms"]
        n_rooms = n_lab + 1  # + vivarium
        margin = 40.0
        gap = 24.0
        usable_w = 1000.0 - 2 * margin
        room_w = (usable_w - gap * (n_rooms - 1)) / n_rooms
        room_h = 1000.0 - 2 * margin

        # spread freezers across the lab rooms, round-robin
        freezers_per_room = [0] * n_lab
        for f in range(self.cfg["freezers"]):
            freezers_per_room[f % n_lab] += 1

        for ri in range(n_rooms):
            rx = margin + ri * (room_w + gap)
            is_vivarium = ri == n_lab
            if is_vivarium:
                name = f"Room {210 + ri} - Vivarium"
            else:
                name = f"Room {201 + ri} - Wet Lab {ri + 1}"
            room_id = self._new_node(None, "room", name, floor_id=1,
                                     box=(rx, margin, room_w, room_h))
            inner = (rx + 16, margin + 16, room_w - 32, room_h - 32)
            if is_vivarium:
                self._fill_vivarium(room_id, inner)
            else:
                self._fill_lab_room(room_id, inner, freezers_per_room[ri])

        self.conn.executemany(
            "INSERT INTO location_node "
            "(id, parent_id, kind, name, capacity_rows, capacity_cols, "
            " floor_id, map_x, map_y, map_w, map_h) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            self.nodes)

    def _fill_lab_room(self, room_id, inner, n_freezers):
        # drawable units inside the room: freezers, a fridge, a cabinet, benches
        units = (["freezer"] * n_freezers) + ["fridge", "cabinet", "bench", "bench"]
        rects = grid_pack(*inner, n=len(units), pad=10.0)
        fcount = 0
        gcount = 0
        for kind, rect in zip(units, rects):
            if kind == "freezer":
                fcount += 1
                fid = self._new_node(room_id, "freezer", f"-80C Freezer {fcount}",
                                     floor_id=1, box=rect)
                self._fill_freezer(fid)
            elif kind == "fridge":
                self._new_node(room_id, "fridge", "4C Fridge", floor_id=1, box=rect)
            elif kind == "cabinet":
                self._new_node(room_id, "cabinet", "Flammables Cabinet",
                               floor_id=1, box=rect)
            else:
                gcount += 1
                self._new_node(room_id, "bench", f"Bench {gcount}",
                               floor_id=1, box=rect)

    def _fill_freezer(self, freezer_id):
        # shelves + boxes live INSIDE the freezer: drilled into, not drawn.
        n_boxes = self.cfg["boxes_per_freezer"]
        n_shelves = min(3, max(1, (n_boxes + 1) // 2))
        shelves = [self._new_node(freezer_id, "shelf", f"Shelf {s + 1}")
                   for s in range(n_shelves)]
        for b in range(n_boxes):
            shelf = shelves[b % n_shelves]
            label = f"Box {chr(65 + (b % 26))}{b + 1}"
            bid = self._new_node(shelf, "box", label, rows=9, cols=9)
            self.boxes.append(bid)

    def _fill_vivarium(self, room_id, inner):
        n_racks = 2 if self.cfg["rooms"] <= 1 else 3
        rack_rects = grid_pack(*inner, n=n_racks, pad=14.0)
        cages_per_rack = max(3, math.ceil(self.cfg["animals"] / (2 * n_racks)))
        for i, rect in enumerate(rack_rects):
            rid = self._new_node(room_id, "rack", f"Rack {i + 1}",
                                 floor_id=1, box=rect)
            rx, ry, rw, rh = rect
            ch = (rh - 8) / cages_per_rack
            for c in range(cages_per_rack):
                cage_name = f"{chr(65 + i)}{c + 1}"
                cage_box = (round(rx + 6, 1), round(ry + 6 + c * ch, 1),
                            round(rw - 12, 1), round(ch - 6, 1))
                self._new_node(rid, "cage", cage_name, floor_id=1, box=cage_box)
                self.cages.append(cage_name)

    # ---- equipment registry + booking + maintenance ------------------------ #
    # (name, category, make_model, serial, location kind, status,
    #  purchase_date offset (days before today), service_interval_days,
    #  last_service offset (days before today), next_service offset (days
    #  from today; negative = already past due)). The first two rows are
    #  PINNED (not rng) so a maintenance_due notification always fires: one
    #  already past due, one due within the 14-day window.
    EQUIPMENT_SPECS = [
        ("Microcentrifuge", "centrifuge", "Eppendorf 5424R", "EP5424R-2201",
         "bench", "operational", 1240, 365, 380, -14),          # PAST DUE
        ("Benchtop Centrifuge", "centrifuge", "Thermo Sorvall ST8",
         "ST8-88421", "bench", "operational", 1510, 365, 359, 6),  # due soon
        ("Thermal Cycler", "thermal cycler", "Bio-Rad C1000 Touch",
         "C1000-556723", "bench", "operational", 1710, 365, 246, 119),
        ("Inverted Microscope", "microscope", "Zeiss Axio Observer 5",
         "AXIO-778812", "bench", "maintenance", 2150, 180, 108, 72),
        ("ULT Freezer", "freezer", "Thermo TSX600A", "TSX600A-33210",
         "freezer", "operational", 2670, 180, 153, 27),
        ("Biosafety Cabinet", "biosafety cabinet", "Baker SterilGARD e3",
         "SG403-90112", "cabinet", "operational", 1990, 365, 215, 150),
    ]

    def gen_equipment(self):
        """Six realistic instruments placed at real generated locations
        (bench/freezer/cabinet nodes, falling back to the first room if a
        preset didn't roll that kind). Deterministic day offsets (not rng)
        guarantee one instrument is already past due for service and one is
        due within 14 days, matching the hand-written seed.sql demo."""
        def node_for(kind):
            picks = [n[0] for n in self.nodes if n[2] == kind]
            if not picks:
                picks = [n[0] for n in self.nodes if n[2] == "room"]
            return picks

        pools = {kind: node_for(kind) for kind in ("bench", "freezer", "cabinet")}
        bench_i = 0
        rows = []
        self.equipment_ids = []
        for i, (name, cat, make_model, serial, kind, status, purchase_off,
                interval, last_off, next_off) in enumerate(
                    self.EQUIPMENT_SPECS, start=1):
            pool = pools.get(kind) or [self.nodes[0][0]]
            if kind == "bench" and len(pool) > 1:
                loc = pool[bench_i % len(pool)]
                bench_i += 1
            else:
                loc = pool[0]
            purchase = self.today - timedelta(days=purchase_off)
            last = self.today - timedelta(days=last_off)
            nxt = self.today + timedelta(days=next_off)
            note = ("Stage motor replaced; pending final calibration."
                    if status == "maintenance" else None)
            rows.append((i, name, cat, make_model, serial, loc, status,
                        iso(purchase), interval, iso(last), iso(nxt), note))
            self.equipment_ids.append(i)
        self.conn.executemany(
            "INSERT INTO equipment (id, name, category, make_model, "
            "serial_number, location_id, status, purchase_date, "
            "service_interval_days, last_service_date, next_service_date, "
            "note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.n_equipment = len(rows)

    def gen_equipment_reservations(self):
        """A handful of upcoming bookings (member/manager), one per distinct
        future day so no two reservations can overlap regardless of which
        equipment id they land on."""
        equip_ids = getattr(self, "equipment_ids", [])
        users = self.conn.execute(
            "SELECT id, username FROM app_user WHERE username IN "
            "('manager', 'member') ORDER BY id").fetchall() or \
            self.conn.execute(
                "SELECT id, username FROM app_user ORDER BY id LIMIT 2"
            ).fetchall()
        if not equip_ids or not users:
            return
        purposes = ["Serum separation for cell culture prep",
                    "Genotyping PCR run for cohort B",
                    "Imaging fixed sections for Aim 2",
                    "Plasma spin-down", "Sterile media prep"]
        day_offsets = [5, 6, 7, 10, 11]
        rows = []
        for i, offset in enumerate(day_offsets):
            eid = equip_ids[i % len(equip_ids)]
            user = users[i % len(users)][0]
            day = self.today + timedelta(days=offset)
            start = f"{iso(day)} {9 + i:02d}:00:00"
            end = f"{iso(day)} {10 + i:02d}:30:00"
            created = self._stamp(self.today - timedelta(days=1))
            rows.append((i + 1, eid, user, start, end,
                        purposes[i % len(purposes)], created))
        self.conn.executemany(
            "INSERT INTO equipment_reservation (id, equipment_id, user_id, "
            "starts_at, ends_at, purpose, created_at) VALUES (?,?,?,?,?,?,?)",
            rows)
        self.n_equipment_reservation = len(rows)

    def gen_equipment_maintenance(self):
        """One past service record per instrument, performed_at/next_due
        matching the equipment row's last/next_service_date so the two
        stay consistent."""
        equip_rows = self.conn.execute(
            "SELECT id, last_service_date, next_service_date FROM equipment "
            "ORDER BY id").fetchall()
        performers = ["A. Rivera", "Eppendorf Field Service", "J. Chen",
                      "Zeiss Field Engineer", "M. Okafor", "Thermo Field Service"]
        rows = []
        for idx, (eid, last, nxt) in enumerate(equip_rows):
            if last is None:
                continue
            kind = "preventive" if idx % 2 == 0 else "calibration"
            rows.append((idx + 1, eid, kind, last, performers[idx % len(performers)],
                        "Routine service; passed inspection.", nxt))
        self.conn.executemany(
            "INSERT INTO equipment_maintenance (id, equipment_id, kind, "
            "performed_at, performed_by, note, next_due) VALUES "
            "(?,?,?,?,?,?,?)", rows)
        self.n_equipment_maintenance = len(rows)

    # ---- protocols -------------------------------------------------------- #
    def gen_protocols(self):
        n = self.cfg["protocols"]
        rows = []
        titles = list(PROTOCOL_TITLES)
        self.rng.shuffle(titles)
        # guarantee at least one overdue and one due-soon
        n_overdue = max(1, round(n * self.chaos))
        for i in range(n):
            pid = 101 + i
            title = titles[i % len(titles)]
            pi = self.rng.choice(self.pi_ids)
            approved = self.past_date(200, 420)
            if i < n_overdue:
                renewal = self.past_date(1, 45)          # OVERDUE
            elif i == n_overdue:
                renewal = self.future_date(1, 25)        # due soon
            else:
                renewal = self.future_date(60, 330)      # fine
            status = "active"
            rows.append((pid, title, pi, iso(approved), iso(renewal), status))
        self.protocol_ids = [r[0] for r in rows]
        self.conn.executemany(
            "INSERT INTO protocols (protocol_id, title, pi_staff_id, "
            "approved_date, renewal_due, status) VALUES (?,?,?,?,?,?)", rows)

    # ---- animals ---------------------------------------------------------- #
    def gen_animals(self):
        n = self.cfg["animals"]
        rows = []
        cages = self.cages or ["A1"]
        for i in range(n):
            aid = 1001 + i
            strain = self.rng.choice(STRAINS)
            sex = self.rng.choice(["M", "F"])
            dob = self.past_date(30, 540)
            protocol = self.rng.choice(self.protocol_ids)
            cage = self.rng.choice(cages)
            # most alive so the colony census is meaningful
            status = self.rng.choices(
                ["alive", "euthanized", "transferred"], weights=[85, 10, 5])[0]
            rows.append((aid, strain, sex, iso(dob), protocol, cage, status))
        self.conn.executemany(
            "INSERT INTO animals (animal_id, strain, sex, date_of_birth, "
            "protocol_id, cage, status) VALUES (?,?,?,?,?,?,?)", rows)

    # ---- inventory + lots ------------------------------------------------- #
    def gen_inventory(self):
        n = self.cfg["items"]
        chaos = self.chaos
        # how many items are stocked out / low / normal
        n_stockout = max(1, round(n * chaos * 0.12))
        low_frac = min(0.65, 0.15 + chaos * 0.5)
        n_low = max(1, round(n * low_frac))
        n_low = min(n_low, n - n_stockout)
        states = (["stockout"] * n_stockout + ["low"] * n_low +
                  ["normal"] * (n - n_stockout - n_low))
        self.rng.shuffle(states)

        # Soft-delete a chaos-tuned handful of items (>=1 always) so the
        # deprecate flow has demo cases. Deprecating never touches quantities,
        # so the on_hand == SUM(lots) invariant is preserved.
        n_dep = min(n, max(1, round(n * self.chaos * 0.05)))
        dep_ids = set(self.rng.sample(range(1, n + 1), n_dep))

        used_names = {}
        item_rows = []
        for i in range(n):
            item_id = i + 1
            cat = CATEGORY_ORDER[i % len(CATEGORY_ORDER)] if i < len(CATEGORY_ORDER) \
                else self.rng.choice(CATEGORY_ORDER)
            names, vendors, units, (clo, chi), expiry_bearing, boxable = \
                ITEM_CATEGORIES[cat]
            base = self.rng.choice(names)
            k = used_names.get(base, 0)
            used_names[base] = k + 1
            name = base if k == 0 else f"{base} #{k + 1}"
            vendor = self.rng.choice(vendors)
            unit = self.rng.choice(units)
            cost = round(self.rng.uniform(clo, chi), 2)
            threshold = self.rng.randint(2, 8)
            state = states[i]
            if state == "stockout":
                on_hand = 0
            elif state == "low":
                on_hand = self.rng.randint(1, threshold)
            else:
                on_hand = self.rng.randint(threshold + 1, threshold * 3 + 6)
            scat = schema_category(cat, name)
            sds_url = (f"https://example.com/sds/{slugify(name)}.pdf"
                       if scat in SDS_CATEGORIES else None)
            disposal = DISPOSAL_BY_CATEGORY.get(scat)
            status = "deprecated" if item_id in dep_ids else "active"
            base = name.split(" #")[0]        # drop any " #2" dedup suffix
            # Wave 2 metadata: GHS hazard class + CAS (chemicals only), a
            # "top up to" reorder_max (~2-3x reorder_threshold), and a soft link
            # to the bundled vendor_catalog product this stock was sourced from.
            hazard_class = CHEMICAL_HAZARDS.get(base)
            cas_number = CHEMICAL_CAS.get(base)
            reorder_max = threshold * 2 + self.rng.randint(1, max(1, threshold))
            catalog_id = CATALOG_LINK.get(base)
            self.items.append(dict(
                item_id=item_id, name=name, vendor=vendor, unit=unit, cost=cost,
                threshold=threshold, on_hand=on_hand, category=scat,
                sds_url=sds_url, disposal=disposal, status=status,
                expiry_bearing=expiry_bearing, boxable=boxable,
                hazard_class=hazard_class, cas_number=cas_number,
                reorder_max=reorder_max, catalog_id=catalog_id))
            item_rows.append((item_id, name, vendor, unit, on_hand, threshold,
                              cost, scat, sds_url, disposal, status,
                              reorder_max, hazard_class, cas_number, catalog_id))

        # ensure at least one boxable item exists so vials can be placed
        if not any(it["boxable"] for it in self.items):
            self.items[0]["boxable"] = True
            self.items[0]["expiry_bearing"] = True

        self.conn.executemany(
            "INSERT INTO inventory (item_id, item_name, vendor, unit, "
            "quantity_on_hand, reorder_threshold, unit_cost, category, sds_url, "
            "disposal_instructions, status, reorder_max, hazard_class, "
            "cas_number, catalog_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            item_rows)

    # ---- vendor catalog + substitute groups ------------------------------- #
    def gen_catalog(self):
        """Emit the bundled vendor catalog and substitute groups verbatim. This
        data is a fixed set of real products, so its counts are identical for
        every seed (determinism)."""
        self.conn.executemany(
            "INSERT INTO substitute_group (id, name, category, description) "
            "VALUES (?,?,?,?)", SUBSTITUTE_GROUP_ROWS)
        self.conn.executemany(
            "INSERT INTO vendor_catalog (id, vendor, catalog_number, "
            "product_name, category, pack_size, unit, list_price, sds_url, "
            "product_url, cas_number, hazard_class, substitute_group_id, "
            "preference_rank, availability) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", VENDOR_CATALOG_ROWS)
        self.n_vendor_catalog = len(VENDOR_CATALOG_ROWS)
        self.n_substitute_group = len(SUBSTITUTE_GROUP_ROWS)
        next_id = len(VENDOR_CATALOG_ROWS) + 1
        cat_cols = ("INSERT INTO vendor_catalog (id, vendor, catalog_number, "
                    "product_name, category, pack_size, unit, list_price, sds_url, "
                    "product_url, cas_number, hazard_class, substitute_group_id, "
                    "preference_rank, availability) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")

        # POC: seed the curated real molecular-biology catalog (--molbio).
        if self.cfg.get("molbio"):
            molbio = self._molbio_rows(next_id)
            self.conn.executemany(cat_cols, molbio)
            self.n_vendor_catalog += len(molbio)
            next_id += len(molbio)

        # Wave 4: procedurally bulk up the catalog for stress-testing long
        # lists / search / pagination. Off by default (--catalog 0). Synthetic
        # rows continue id numbering after the fixed + curated sets and leave
        # substitute_group_id / preference_rank NULL.
        n_extra = self.cfg.get("catalog", 0)
        if n_extra and n_extra > 0:
            synth = self._synth_catalog_rows(n_extra, next_id)
            self.conn.executemany(cat_cols, synth)
            self.n_vendor_catalog += len(synth)

    # Vendor -> (product-page domain) for building plausible URLs on curated rows.
    _MOLBIO_VENDOR_DOMAIN = {
        "NEB": "neb.com", "Sigma-Aldrich": "sigmaaldrich.com",
        "Thermo Fisher": "thermofisher.com", "Invitrogen": "thermofisher.com",
        "Applied Biosystems": "thermofisher.com", "QIAGEN": "qiagen.com",
        "Promega": "promega.com", "Eppendorf": "eppendorf.com", "Corning": "corning.com",
    }

    def _molbio_rows(self, start_id):
        """Expand the curated MOLBIO_CATALOG specs into full vendor_catalog tuples."""
        rows = []
        for k, spec in enumerate(MOLBIO_CATALOG):
            name, vendor, catnum, category, pack, unit, price, cas, hazard = spec
            domain = self._MOLBIO_VENDOR_DOMAIN.get(vendor, "example-vendor.com")
            product_url = f"https://www.{domain}/product/{catnum}"
            sds_url = (f"https://www.{domain}/sds/{catnum}") if category == "chemical" else None
            rows.append((
                start_id + k, vendor, catnum, name, category, pack, unit, price,
                sds_url, product_url, cas, hazard, None, None, "in_stock",
            ))
        return rows

    def _synth_catalog_rows(self, count, start_id):
        """Synthesize `count` realistic vendor_catalog rows via the seeded rng,
        with ids starting at start_id. Deterministic under --seed."""
        rng = self.rng
        rows = []
        for k in range(count):
            cid = start_id + k
            category = rng.choices(SYNTH_CATEGORY_POOL,
                                   weights=SYNTH_CATEGORY_WEIGHTS)[0]
            vendor = rng.choice(CATALOG_CATEGORY_VENDORS[category])
            shape_fn, sds_fn, prod_fn = VENDOR_SPECS[vendor]
            catnum = shape_fn(rng)
            names, quals = SYNTH_PRODUCTS[category]
            base = rng.choice(names)
            product_name = (f"{base}, {rng.choice(quals)}"
                            if quals and rng.random() < 0.7 else base)
            pack_size, unit = rng.choice(SYNTH_PACKS[category])
            lo, hi = SYNTH_PRICE[category]
            list_price = round(rng.uniform(lo, hi), 2)
            cas_number = None
            hazard_class = None
            if category == "chemical":
                # POC: give most synthetic chemicals a REAL identity (name + CAS +
                # hazards) drawn from the curated pool, so the catalog reads like a
                # real reagent list rather than invented names.
                if REAL_CHEMICALS and rng.random() < 0.85:
                    product_name, cas_number, hazard_class = rng.choice(REAL_CHEMICALS)
                else:
                    if rng.random() < 0.92:
                        cas_number = _synth_cas(rng)
                    if rng.random() < 0.6:
                        hazard_class = _synth_hazard(rng)
            elif category == "reagent":
                if rng.random() < 0.20:
                    cas_number = _synth_cas(rng)
                if rng.random() < 0.12:
                    hazard_class = _synth_hazard(rng)
            availability = rng.choices(
                ["in_stock", "backorder", "discontinued"],
                weights=[80, 14, 6])[0]
            rows.append((cid, vendor, catnum, product_name, category, pack_size,
                         unit, list_price, sds_fn(catnum), prod_fn(catnum),
                         cas_number, hazard_class, None, None, availability))
        return rows

    def gen_lots(self):
        chaos = self.chaos
        expired_frac = min(0.6, 0.10 + chaos * 0.40)
        expiring_frac = 0.18
        # fraction of eligible lots that carry a Certificate of Analysis; more
        # chaos -> more paperwork floating around (still deterministic via rng).
        coa_frac = min(0.7, 0.20 + chaos * 0.45)
        expired_ct = 0
        expiring_ct = 0
        lot_rows = []
        for it in self.items:
            on_hand = it["on_hand"]
            n_lots = 1 if on_hand == 0 else self.rng.choice([1, 1, 2, 2, 3])
            quantities = partition(on_hand, n_lots, self.rng)
            for q in quantities:
                self._lot_id += 1
                lot_id = self._lot_id
                prefix = "".join(w[0] for w in it["name"].split()[:2]).upper() or "LOT"
                lot_number = f"{prefix}-{self.rng.randint(1000, 9999)}"
                received = self.past_date(20, min(self.cfg['days'], 400))
                if not it["expiry_bearing"]:
                    expiry = None
                else:
                    roll = self.rng.random()
                    if roll < expired_frac:
                        expiry = self.past_date(3, 220)
                        expired_ct += 1
                    elif roll < expired_frac + expiring_frac:
                        expiry = self.future_date(1, 30)
                        expiring_ct += 1
                    else:
                        expiry = self.future_date(45, 560)
                coa_url = None
                if it["category"] in COA_CATEGORIES and self.rng.random() < coa_frac:
                    coa_url = f"https://example.com/coa/{lot_number}.pdf"
                lot = dict(id=lot_id, item_id=it["item_id"], lot_number=lot_number,
                           expiry=expiry, quantity=q, received=received,
                           boxable=it["boxable"], coa_url=coa_url)
                self.lots.append(lot)
                lot_rows.append(lot)

        # guarantee at least one expired and one expiring lot show up
        bearing = [ln for ln in self.lots if any(
            it["item_id"] == ln["item_id"] and it["expiry_bearing"] for it in self.items)]
        if bearing and expired_ct == 0:
            bearing[0]["expiry"] = self.past_date(3, 60)
        if bearing and expiring_ct == 0:
            target = bearing[-1] if len(bearing) > 1 else bearing[0]
            target["expiry"] = self.future_date(1, 28)

        self.conn.executemany(
            "INSERT INTO item_lot (id, item_id, lot_number, expiry_date, "
            "quantity, received_date, coa_url) VALUES (?,?,?,?,?,?,?)",
            [(ln["id"], ln["item_id"], ln["lot_number"],
              iso(ln["expiry"]) if ln["expiry"] else None,
              ln["quantity"], iso(ln["received"]), ln["coa_url"]) for ln in self.lots])

    # ---- containers ------------------------------------------------------- #
    def gen_containers(self):
        boxable_lots = [ln["id"] for ln in self.lots if ln["boxable"]]
        if not boxable_lots or not self.boxes:
            self.container_rows = []
            return
        rows = []
        for box_id in self.boxes:
            cap = 81
            target = min(cap, self.rng.randint(8, 50))
            wells = self.rng.sample(
                [(r, c) for r in range(1, 10) for c in range(1, 10)], target)
            for (r, c) in wells:
                self._container_id += 1
                cid = self._container_id
                lot_id = self.rng.choice(boxable_lots)
                # correctly placed: actual == expected
                rows.append([cid, lot_id, box_id, r, c, box_id, r, c, "in_use"])

        # misplace a chaos-tuned fraction: keep ACTUAL well (unique), scramble
        # only the EXPECTED coords so no two in_use share a real well.
        n_mis = max(1, round(len(rows) * (0.05 + self.chaos * 0.35)))
        for row in self.rng.sample(rows, min(n_mis, len(rows))):
            while True:
                ebox = self.rng.choice(self.boxes)
                er = self.rng.randint(1, 9)
                ec = self.rng.randint(1, 9)
                if (ebox, er, ec) != (row[2], row[3], row[4]):
                    break
            row[5], row[6], row[7] = ebox, er, ec

        self.container_rows = rows
        self.conn.executemany(
            "INSERT INTO container (id, item_lot_id, box_id, row, col, "
            "expected_box_id, expected_row, expected_col, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)

    # ---- storage-compatibility conflict (demo) ---------------------------- #
    def gen_storage_conflict(self):
        """Guarantee an INTENTIONAL storage-segregation violation so the Safety
        view always has a conflict to show. We find a box that already holds two
        DISTINCT items (so they share a storage unit) and force an incompatible
        GHS pair on them: item A = flammable, item B = oxidizer -> flammable +
        oxidizer DANGER. This is deterministic (no rng), adds NO location or
        container rows, and never touches item_lot.quantity, so the
        quantity_on_hand == SUM(quantity) invariant is preserved."""
        rows = getattr(self, "container_rows", [])
        if not rows or len(self.items) < 2:
            return
        lot_item = {ln["id"]: ln["item_id"] for ln in self.lots}
        by_box = {}
        for row in rows:                      # row = [cid, lot_id, box_id, ...]
            item_id = lot_item.get(row[1])
            if item_id is None:
                continue
            seen = by_box.setdefault(row[2], [])
            if item_id not in seen:
                seen.append(item_id)
        pair = next((seen[:2] for box_id in sorted(by_box)
                     for seen in [by_box[box_id]] if len(seen) >= 2), None)
        if not pair:
            return
        by_id = {it["item_id"]: it for it in self.items}
        for item_id, hazard in zip(pair, ["flammable,irritant",
                                          "oxidizer,irritant"]):
            by_id[item_id]["hazard_class"] = hazard
            self.conn.execute(
                "UPDATE inventory SET hazard_class=? WHERE item_id=?",
                (hazard, item_id))

    # ---- kits (bill-of-materials) ------------------------------------------ #
    # Recipe archetypes mirroring seed.sql's Wave 3 batch 2 kits: (category,
    # preferred base names) per component. If this preset/seed didn't roll an
    # item with that exact name, we fall back to the highest-stock item in the
    # same category so the kit is still realistic and (usually) assemblable.
    KIT_RECIPES = [
        ("4% PFA fixative (500 mL)",
         "Working perfusion/immersion fixative diluted from stock "
         "paraformaldehyde and PBS.",
         [("chemical", ["4% Paraformaldehyde"]), ("reagent", ["PBS 10x"])]),
        ("Genotyping PCR master mix",
         "Standard Taq-based master mix for tail/ear-clip genotyping PCR.",
         [("enzyme", ["Taq DNA Polymerase"]), ("enzyme", ["dNTP Mix 10mM"])]),
        ("Immunostaining block buffer",
         "Serum-based blocking buffer for fluorescent immunohistochemistry.",
         [("media", ["Fetal Bovine Serum"]), ("reagent", ["PBS 10x"])]),
    ]

    def gen_kits(self):
        """Emit 2-3 kits (bill-of-materials) from real generated items.
        Quantity per component is always 1, so max_assemblies == that
        component's on_hand -- assemblable whenever the picked item has any
        stock. Deterministic given the seed (candidate selection is by
        highest on_hand, not rng)."""
        def base_name(it):
            return it["name"].split(" #")[0]

        def pick(category, names):
            cands = [it for it in self.items
                     if it["category"] == category and base_name(it) in names]
            if not cands:
                cands = [it for it in self.items if it["category"] == category]
            if not cands:
                cands = self.items
            return max(cands, key=lambda it: it["on_hand"])

        kit_rows, line_rows = [], []
        kid = lid = 0
        for name, desc, components in self.KIT_RECIPES:
            picked = [pick(cat, names) for cat, names in components]
            if len({it["item_id"] for it in picked}) < len(picked):
                continue  # degenerate preset (too few distinct items) -- skip
            kid += 1
            kit_rows.append((kid, name, desc, None, 0))
            for it in picked:
                lid += 1
                line_rows.append((lid, kid, it["item_id"], 1))
        self.conn.executemany(
            "INSERT INTO kit (id, name, description, output_item_id, "
            "output_qty) VALUES (?,?,?,?,?)", kit_rows)
        self.conn.executemany(
            "INSERT INTO kit_line (id, kit_id, item_id, quantity) "
            "VALUES (?,?,?,?)", line_rows)
        self.n_kit = len(kit_rows)
        self.n_kit_line = len(line_rows)

    # ---- preparations (in-house mixes: PBS 1x, fresh PFA, aCSF, ...) ------- #
    # Recipe archetypes mirroring seed.sql's Wave 2 preparations: (name,
    # description, category, shelf_life_days, [(category, preferred base
    # names, quantity), ...]). Falls back to the highest-stock item in the
    # same schema category (like KIT_RECIPES) so every recipe is still
    # realistic if this preset/seed didn't roll that exact item name.
    PREP_RECIPES = [
        ("PBS 1x",
         "1x phosphate-buffered saline diluted from 10x stock.",
         "buffer", 30,
         [("reagent", ["PBS 10x"], 1)]),
        ("4% PFA (fresh)",
         "Fresh 4% paraformaldehyde fixative made up from stock and PBS.",
         "fixative", 7,
         [("reagent", ["4% Paraformaldehyde"], 2), ("reagent", ["PBS 10x"], 1)]),
        ("aCSF",
         "Artificial cerebrospinal fluid (component surrogate from buffer "
         "stock; no true aCSF salts in the generated inventory).",
         "buffer", 3,
         [("reagent", ["Tris-HCl 1M pH 8.0"], 1), ("reagent", ["PBS 10x"], 1)]),
        ("Blocking buffer",
         "FBS-based blocking buffer for fluorescent immunostaining.",
         "buffer", 14,
         [("media", ["Fetal Bovine Serum"], 1), ("reagent", ["PBS 10x"], 1)]),
    ]

    def gen_preparations(self):
        """Emit the preparation recipes above from real generated items, plus
        dated batches with a guaranteed expired case and a guaranteed
        expiring-soon case (mirrors gen_kits' bill-of-materials pattern;
        component selection is deterministic, not rng)."""
        def pick(category, names):
            cands = [it for it in self.items if it["category"] == category
                     and it["name"].split(" #")[0] in names]
            if not cands:
                cands = [it for it in self.items if it["category"] == category]
            if not cands:
                cands = self.items
            return max(cands, key=lambda it: it["on_hand"])

        prep_rows, line_rows, created = [], [], []
        pid = lid = 0
        for name, desc, category, shelf_life, components in self.PREP_RECIPES:
            picked = [(pick(cat, names), qty) for cat, names, qty in components]
            if len({it["item_id"] for it, _ in picked}) < len(picked):
                continue   # degenerate preset (too few distinct items) -- skip
            pid += 1
            prep_rows.append((pid, name, desc, category, shelf_life, None))
            for it, qty in picked:
                lid += 1
                line_rows.append((lid, pid, it["item_id"], qty))
            created.append((pid, name, shelf_life))

        self.conn.executemany(
            "INSERT INTO preparation (id, name, description, category, "
            "shelf_life_days, note) VALUES (?,?,?,?,?,?)", prep_rows)
        self.conn.executemany(
            "INSERT INTO preparation_line (id, preparation_id, item_id, "
            "quantity) VALUES (?,?,?,?)", line_rows)
        self.n_preparation = len(prep_rows)
        self.n_preparation_line = len(line_rows)
        self._gen_preparation_batches(created)

    def _gen_preparation_batches(self, created):
        """created: [(preparation_id, name, shelf_life_days), ...] in recipe
        order. Batch #1 is forced EXPIRED, batch #2 (or #1 again, if only one
        recipe survived) is forced EXPIRING SOON, and every recipe also gets
        one FRESH batch -- so the guarantee holds regardless of preset size."""
        if not created:
            self.n_preparation_batch = 0
            return
        users = self.conn.execute(
            "SELECT id, username FROM app_user WHERE username IN "
            "('manager', 'member') ORDER BY id").fetchall() or \
            self.conn.execute(
                "SELECT id, username FROM app_user ORDER BY id").fetchall()
        maker_ids = [u[0] for u in users] or [None]

        specs = [(created[0], "expired"),
                 (created[1] if len(created) > 1 else created[0], "soon")]
        specs += [(c, "fresh") for c in created]

        rows = []
        bid = 0
        for i, ((pid, name, shelf_life), state) in enumerate(specs):
            bid += 1
            shelf_life = shelf_life or 30
            if state == "expired":
                made_at = self.today - timedelta(days=shelf_life + 3)
            elif state == "soon":
                made_at = self.today - timedelta(days=max(shelf_life - 1, 0))
            else:
                made_at = self.today
            expiry = made_at + timedelta(days=shelf_life)
            prefix = "".join(w[0] for w in name.split()[:2]).upper() or "PREP"
            lot_label = f"{prefix}-{made_at.strftime('%y%m')}{chr(65 + (i % 26))}"
            amount = "1 L" if i % 2 == 0 else "500 mL"
            made_by = maker_ids[i % len(maker_ids)]
            rows.append((bid, pid, lot_label, made_by, self._stamp(made_at),
                        iso(expiry), amount, "in_use", None))

        self.conn.executemany(
            "INSERT INTO preparation_batch (id, preparation_id, lot_label, "
            "made_by, made_at, expiry_date, amount, status, note) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.n_preparation_batch = len(rows)

    # ---- lab maintenance (recurring chores) -------------------------------- #
    # (name, category, interval_days, instructions, placement, guaranteed
    # state, offset). placement picks a real generated location_node by kind
    # ("room" = first lab room, "bench", "vivarium", "freezer"); state/offset
    # deterministically force at least one OVERDUE chore and one DUE-SOON
    # chore (mirrors the preparation-batch guarantee above), the rest "fresh".
    CHORE_SPECS = [
        ("Clean biosafety cabinet", "cleaning", 7,
         "Wipe down the work surface with 70% ethanol; run a 15-minute UV cycle.",
         "room", "overdue", 2),
        ("Autoclave biohazard waste", "autoclave", 3,
         "Autoclave biohazard bags at 121C for 30 minutes; log the cycle.",
         "room", "soon", 2),
        ("Fill DI water tank", "water", 7,
         "Top off the DI water reservoir from the house line; check conductivity.",
         "room", "fresh", None),
        ("Calibrate pipettes", "calibration", 180,
         "Send single-channel pipettes out for gravimetric calibration.",
         "bench", "fresh", None),
        ("Empty sharps containers", "stocking", 14,
         "Seal full sharps containers, replace them, and log the pickup.",
         "vivarium", "fresh", None),
        ("Defrost -80C backup", "other", 365,
         "Defrost and clean the backup ULT freezer; verify alarm wiring.",
         "freezer", "overdue", 15),
    ]

    def gen_chores(self):
        """Emit the recurring chores above at real generated locations, with a
        completion log entry per chore."""
        room_id = next((n[0] for n in self.nodes
                        if n[2] == "room" and "Vivarium" not in n[3]), None)
        vivarium_id = next((n[0] for n in self.nodes
                            if n[2] == "room" and "Vivarium" in n[3]), room_id)
        bench_id = next((n[0] for n in self.nodes if n[2] == "bench"), room_id)
        freezer_id = next((n[0] for n in self.nodes if n[2] == "freezer"),
                          room_id)
        placement = {"room": room_id, "bench": bench_id,
                     "vivarium": vivarium_id, "freezer": freezer_id}

        users = self.conn.execute(
            "SELECT id, username FROM app_user WHERE username IN "
            "('manager', 'member') ORDER BY id").fetchall() or \
            self.conn.execute(
                "SELECT id, username FROM app_user ORDER BY id").fetchall()
        doer_ids = [u[0] for u in users] or [None]

        chore_rows, log_rows = [], []
        cid = lid = 0
        for i, (name, category, interval, instructions, place, state, offset) \
                in enumerate(self.CHORE_SPECS):
            cid += 1
            if state == "overdue":
                next_due = self.today - timedelta(days=offset)
                last_done = next_due - timedelta(days=interval)
            elif state == "soon":
                next_due = self.today + timedelta(days=offset)
                last_done = next_due - timedelta(days=interval)
            else:
                last_done = self.today - timedelta(days=max(1, interval // 6))
                next_due = last_done + timedelta(days=interval)
            chore_rows.append((cid, name, category, placement.get(place),
                               interval, iso(last_done), iso(next_due),
                               instructions, None))
            lid += 1
            doer = doer_ids[i % len(doer_ids)]
            log_rows.append((lid, cid, doer, self._stamp(last_done),
                             f"{name} completed."))

        self.conn.executemany(
            "INSERT INTO chore (id, name, category, location_id, "
            "interval_days, last_done, next_due, instructions, note) "
            "VALUES (?,?,?,?,?,?,?,?,?)", chore_rows)
        self.conn.executemany(
            "INSERT INTO chore_log (id, chore_id, done_by, done_at, note) "
            "VALUES (?,?,?,?,?)", log_rows)
        self.n_chore = len(chore_rows)
        self.n_chore_log = len(log_rows)

    # ---- cycle count / stocktake ------------------------------------------- #
    def gen_counts(self):
        """Emit one CLOSED cycle-count session over a real freezer's subtree,
        built from real generated containers (FK-clean). A chaos-independent
        ~20% of the sampled lines are left 'pending' and roll over to
        'missing' on close -- mirroring the actual /api/counts/{id}/close
        behavior -- so the closed session's accuracy is always below 100%
        whenever the freezer holds at least 2 in_use containers."""
        rows_c = getattr(self, "container_rows", [])
        in_use = [r for r in rows_c if r[8] == "in_use"]
        if not in_use:
            return
        node_by_id = {n[0]: n for n in self.nodes}

        def ancestor_freezer(box_id):
            nid = box_id
            while nid is not None:
                node = node_by_id.get(nid)
                if node is None:
                    return None
                if node[2] == "freezer":
                    return nid
                nid = node[1]
            return None

        freezer_id = next((n[0] for n in self.nodes if n[2] == "freezer"), None)
        if freezer_id is None:
            return
        candidates = [r for r in in_use if ancestor_freezer(r[2]) == freezer_id]
        if not candidates:
            return
        lot_item = {ln["id"]: ln["item_id"] for ln in self.lots}

        n_lines = min(len(candidates), 8)
        n_lines = max(n_lines, min(3, len(candidates)))
        lines = self.rng.sample(candidates, n_lines)
        n_missing = max(1, round(n_lines * 0.2))
        missing_lines, found_lines = lines[:n_missing], lines[n_missing:]

        users = self.conn.execute(
            "SELECT id FROM app_user WHERE username='manager'").fetchone() or \
            self.conn.execute("SELECT id FROM app_user ORDER BY id LIMIT 1").fetchone()
        manager_id = users[0]

        started_day = self.today - timedelta(days=1)
        started_at = f"{iso(started_day)} 09:00:00"
        closed_at = f"{iso(started_day)} 10:15:00"

        self.conn.execute(
            "INSERT INTO count_session (id, location_id, name, status, "
            "started_by, started_at, closed_at, note) VALUES (?,?,?,?,?,?,?,?)",
            (1, freezer_id, f"{node_by_id[freezer_id][3]} cycle count",
             "closed", manager_id, started_at, closed_at,
             "Routine cycle count."))

        line_rows = []
        lline_id = 0
        for r in missing_lines:
            lline_id += 1
            box_name = node_by_id[r[2]][3]
            line_rows.append((lline_id, 1, r[0], lot_item.get(r[1]), box_name,
                              r[3], r[4], 1, None, "missing", None, None))
        for i, r in enumerate(found_lines):
            lline_id += 1
            box_name = node_by_id[r[2]][3]
            minute = 5 + i * 3
            hour, minute = (9, minute) if minute < 60 else (10, minute - 60)
            ts = f"{iso(started_day)} {hour:02d}:{minute:02d}:00"
            line_rows.append((lline_id, 1, r[0], lot_item.get(r[1]), box_name,
                              r[3], r[4], 1, 1, "found", ts, manager_id))
        self.conn.executemany(
            "INSERT INTO count_line (id, session_id, container_id, item_id, "
            "box_name, row, col, expected, counted, status, counted_at, "
            "counted_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", line_rows)
        self.n_count_session = 1
        self.n_count_line = len(line_rows)

    # ---- orders ----------------------------------------------------------- #
    def gen_orders(self):
        days = self.cfg["days"]
        oid = 0
        rows = []
        self.orders = []
        for it in self.items:
            n_orders = self.rng.randint(1, 4)
            for _ in range(n_orders):
                oid += 1
                offset = self.rng.randint(0, days)
                order_date = self.today - timedelta(days=offset)
                qty = self.rng.randint(1, 10)
                unit_cost = round(it["cost"] * self.rng.uniform(0.9, 1.1), 2)
                staff = self.rng.choice(self.staff_ids)
                rows.append((oid, it["item_id"], qty, iso(order_date),
                             unit_cost, staff))
                self.orders.append(dict(item_id=it["item_id"], qty=qty,
                                        date=order_date, staff=staff))
        self.conn.executemany(
            "INSERT INTO orders (order_id, item_id, quantity, order_date, "
            "unit_cost, ordered_by) VALUES (?,?,?,?,?,?)", rows)

    # ---- training --------------------------------------------------------- #
    def gen_training(self):
        rows = []
        tid = 0
        chaos = self.chaos
        entries = []
        for sid in self.staff_ids:
            for course in self.rng.sample(TRAINING_COURSES,
                                          self.rng.randint(1, 3)):
                entries.append((sid, course))
        n_expired = max(1, round(len(entries) * chaos * 0.4))
        n_expiring = max(1, round(len(entries) * 0.15))
        self.rng.shuffle(entries)
        for i, (sid, course) in enumerate(entries):
            tid += 1
            if i < n_expired:
                completed = self.past_date(400, 900)
                expires = self.past_date(1, 120)            # EXPIRED
            elif i < n_expired + n_expiring:
                completed = self.past_date(300, 700)
                expires = self.future_date(1, 60)           # expiring soon
            else:
                completed = self.past_date(60, 400)
                expires = self.future_date(120, 700)        # fine
            rows.append((tid, sid, course, iso(completed), iso(expires)))
        self.conn.executemany(
            "INSERT INTO training (training_id, staff_id, course, "
            "completed_date, expires_date) VALUES (?,?,?,?,?)", rows)

    # ---- usage events ----------------------------------------------------- #
    def gen_usage_events(self):
        days = self.cfg["days"]
        start = self.today - timedelta(days=days - 1)
        rows = []
        eid = 0
        # per-item base consumption rate (events/day) + typical draw size
        for it in self.items:
            base_rate = self.rng.uniform(0.05, 0.4)
            draw_hi = self.rng.choice([1, 2, 3, 4])
            for d in range(days):
                day = start + timedelta(days=d)
                weekend = day.weekday() >= 5
                lam = base_rate * (0.3 if weekend else 1.0)
                # small counts: usually 0 or 1, occasionally 2
                n_events = 0
                if self.rng.random() < min(0.9, lam):
                    n_events = 1
                    if self.rng.random() < lam * 0.5:
                        n_events = 2
                for _ in range(n_events):
                    eid += 1
                    qty = self.rng.randint(1, draw_hi)
                    ts = self._stamp(day)
                    staff = self.rng.choice(self.staff_ids)
                    rows.append((eid, it["item_id"], None, staff, "consume",
                                 qty, ts, None))

        # restock events tied to a subset of orders
        for o in self.orders:
            if self.rng.random() < 0.5:
                eid += 1
                rows.append((eid, o["item_id"], None, o["staff"], "restock",
                             o["qty"], self._stamp(o["date"]),
                             "PO received"))

        # a handful of move events referencing real containers
        cont_ids = [r[0] for r in getattr(self, "container_rows", [])]
        if cont_ids:
            for _ in range(min(len(cont_ids), max(2, round(self.chaos * 12)))):
                eid += 1
                cid = self.rng.choice(cont_ids)
                day = self.past_date(1, days)
                rows.append((eid, None, cid, self.rng.choice(self.staff_ids),
                             "move", None, self._stamp(day), "Reorg"))

        rows.sort(key=lambda r: (r[6], r[0]))
        # renumber ids so they are contiguous & ordered by time (stable, tidy)
        rows = [(i + 1,) + r[1:] for i, r in enumerate(rows)]
        self.conn.executemany(
            "INSERT INTO usage_event (id, item_id, container_id, staff_id, "
            "event_type, quantity, occurred_at, note) VALUES (?,?,?,?,?,?,?,?)",
            rows)
        self.n_events = len(rows)

    def _stamp(self, day):
        t = f"{self.rng.randint(8, 18):02d}:{self.rng.randint(0, 59):02d}:" \
            f"{self.rng.randint(0, 59):02d}"
        return f"{iso(day)} {t}"

    # ---- settings --------------------------------------------------------- #
    def gen_settings(self):
        # usage_visibility gates per-person usage; po_approval_threshold is the
        # dollar ceiling under which a requisition auto-approves (text, parsed
        # as a number by the app).
        self.conn.executemany(
            "INSERT INTO app_setting (key, value) VALUES (?, ?)",
            [("usage_visibility", "admin_only"),
             ("po_approval_threshold", "500")])

    # ---- task templates --------------------------------------------------- #
    def gen_task_templates(self):
        by_cat = {}
        for it in self.items:
            by_cat.setdefault(it["category"], []).append(it["item_id"])
        all_ids = [it["item_id"] for it in self.items]

        tt_rows, ttl_rows = [], []
        ttl_id = 0
        self.templates = []
        for tid, (name, desc, specs) in enumerate(TEMPLATE_SPECS, start=1):
            tt_rows.append((tid, name, desc))
            used, lines = set(), []
            for cat, qty in specs:
                pool = [i for i in by_cat.get(cat, []) if i not in used] \
                    or [i for i in all_ids if i not in used] or all_ids
                item_id = self.rng.choice(pool)
                used.add(item_id)
                ttl_id += 1
                ttl_rows.append((ttl_id, tid, item_id, qty))
                lines.append((item_id, qty))
            self.templates.append(dict(id=tid, name=name, lines=lines))

        self.conn.executemany(
            "INSERT INTO task_template (id, name, description) VALUES (?,?,?)",
            tt_rows)
        self.conn.executemany(
            "INSERT INTO task_template_line "
            "(id, template_id, item_id, default_quantity) VALUES (?,?,?,?)",
            ttl_rows)

    # ---- tickets + matching usage/audit ----------------------------------- #
    def gen_tickets(self):
        # app_user was populated by ensure_demo_users (ids 1..4). Prefer the
        # bench workers (manager, member); viewers/admins do occasional entries.
        users = self.conn.execute(
            "SELECT id, username, staff_id FROM app_user ORDER BY id").fetchall()
        by_name = {u[1]: u for u in users}
        pool = [by_name[n] for n in ("manager", "member", "manager", "member",
                                     "viewer") if n in by_name] or users

        window = 14
        n_tickets = self.rng.randint(6, 10)
        self._audit_rows = []
        self._audit_id = 0
        usage_rows = []
        uid = self.n_events            # continue after gen_usage_events ids
        ticket_rows, line_rows = [], []
        line_id = 0

        for tid in range(1, n_tickets + 1):
            uid_row = self.rng.choice(pool)
            user_id, username, u_staff = uid_row[0], uid_row[1], uid_row[2]
            staff_id = u_staff if u_staff in self.staff_ids \
                else self.rng.choice(self.staff_ids)
            tmpl = self.rng.choice(self.templates)
            day = self.today - timedelta(days=self.rng.randint(0, window))
            purpose = tmpl["name"]
            ts = self._stamp(day)
            ticket_rows.append((tid, user_id, iso(day), tmpl["name"], purpose,
                                None, ts))
            self._audit(ts, user_id, username, "ticket.create", "ticket", tid,
                        f"{tmpl['name']} ticket")
            # 1..3 lines drawn from the template's items
            k = self.rng.randint(1, min(3, len(tmpl["lines"])))
            for (item_id, qty) in self.rng.sample(tmpl["lines"], k):
                line_id += 1
                line_rows.append((line_id, tid, item_id, qty))
                uid += 1
                uts = self._stamp(day)
                usage_rows.append((uid, item_id, None, staff_id, "consume",
                                   qty, uts, None, tid, purpose))
                self._audit(uts, user_id, username, "consume", "inventory",
                            item_id, f"item #{item_id} x{qty} ({purpose})")

        self.conn.executemany(
            "INSERT INTO ticket (id, user_id, ticket_date, task, purpose, note, "
            "created_at) VALUES (?,?,?,?,?,?,?)", ticket_rows)
        self.conn.executemany(
            "INSERT INTO ticket_line (id, ticket_id, item_id, quantity) "
            "VALUES (?,?,?,?)", line_rows)
        self.conn.executemany(
            "INSERT INTO usage_event (id, item_id, container_id, staff_id, "
            "event_type, quantity, occurred_at, note, ticket_id, purpose) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", usage_rows)
        self.n_events = uid
        self.n_tickets = n_tickets

    def _audit(self, ts, user_id, username, action, etype, eid, detail):
        self._audit_id += 1
        self._audit_rows.append(
            (self._audit_id, ts, user_id, username, action, etype, eid, detail))

    def gen_audit_log(self):
        """Round out the audit trail with non-ticket activity so History
        mirrors the wider world: logins, restocks, a settings change, the
        deprecations, and a couple container moves."""
        users = self.conn.execute(
            "SELECT id, username FROM app_user ORDER BY id").fetchall()
        # a login per user over the window
        for (uid, uname) in users:
            day = self.today - timedelta(days=self.rng.randint(0, 14))
            self._audit(self._stamp(day), uid, uname, "login", None, None,
                        "session start")
        admin = next((u for u in users if u[1] == "admin"), users[0])
        mgr = next((u for u in users if u[1] == "manager"), users[0])
        # settings change
        self._audit(self._stamp(self.today - timedelta(days=13)),
                    admin[0], admin[1], "settings.update", "app_setting", None,
                    "usage_visibility -> admin_only")
        # deprecations mirrored
        for it in self.items:
            if it["status"] == "deprecated":
                day = self.today - timedelta(days=self.rng.randint(0, 14))
                self._audit(self._stamp(day), admin[0], admin[1],
                            "item.deprecate", "inventory", it["item_id"],
                            f"{it['name']} marked deprecated")
        # a few restocks drawn from real orders
        for o in self.rng.sample(self.orders, min(len(self.orders), 4)):
            self._audit(self._stamp(o["date"]), mgr[0], mgr[1], "restock",
                        "inventory", o["item_id"],
                        f"item #{o['item_id']} +{o['qty']} (PO received)")
        # container moves
        cont_ids = [r[0] for r in getattr(self, "container_rows", [])]
        for cid in self.rng.sample(cont_ids, min(len(cont_ids), 3)):
            day = self.today - timedelta(days=self.rng.randint(0, 14))
            self._audit(self._stamp(day), mgr[0], mgr[1], "container.move",
                        "container", cid, "Reorg")

        self._audit_rows.sort(key=lambda r: (r[1], r[0]))
        rows = [(i + 1,) + r[1:] for i, r in enumerate(self._audit_rows)]
        self.conn.executemany(
            "INSERT INTO audit_log (id, occurred_at, user_id, username, action, "
            "entity_type, entity_id, detail) VALUES (?,?,?,?,?,?,?,?)", rows)
        self.n_audit = len(rows)

    # ---- controlled-substance register ------------------------------------ #
    def gen_controlled(self):
        """Flag a small number of anesthetic/controlled items and lay down a
        DEA-style running-balance register for each: an opening received entry
        (+R) followed by signed dispenses that draw the balance down to the
        item's quantity_on_hand, each with a reason and a witness signature."""
        users = self.conn.execute(
            "SELECT id, username FROM app_user WHERE username IN "
            "('manager','member') ORDER BY id").fetchall() or \
            self.conn.execute(
                "SELECT id, username FROM app_user ORDER BY id").fetchall()

        # pick items whose base name is a known controlled drug
        controlled = []
        for it in self.items:
            base = it["name"].split(" #")[0]
            if base in CONTROLLED_SCHEDULES and it["status"] == "active":
                controlled.append((it, CONTROLLED_SCHEDULES[base]))
        # guarantee at least one: fall back to an active chemical item as Sch III
        if not controlled:
            fallback = next((it for it in self.items
                             if it["category"] == "chemical"
                             and it["status"] == "active"), self.items[0])
            controlled.append((fallback, "III"))
        controlled = controlled[:2]                # keep it realistic (<=2)
        self.controlled_items = controlled

        log_rows = []
        log_id = 0
        for it, sched in controlled:
            self.conn.execute(
                "UPDATE inventory SET is_controlled = 1, "
                "controlled_schedule = ? WHERE item_id = ?",
                (sched, it["item_id"]))
            on_hand = it["on_hand"]
            n_disp = self.rng.randint(3, 5)
            draws = [self.rng.randint(1, 2) for _ in range(n_disp)]
            received = on_hand + sum(draws)        # so the register ends at on_hand
            # distinct, sorted day offsets: oldest = the received entry
            offsets = sorted(self.rng.sample(range(1, 90), n_disp + 1),
                             reverse=True)
            u = self.rng.choice(users)
            log_id += 1
            balance = received
            log_rows.append((log_id, it["item_id"],
                             self._stamp(self.today - timedelta(days=offsets[0])),
                             u[0], u[1], received, balance,
                             "Received shipment", self.rng.choice(STAFF_NAMES)))
            for i, d in enumerate(draws):
                balance -= d
                u = self.rng.choice(users)
                log_id += 1
                log_rows.append((log_id, it["item_id"],
                                 self._stamp(self.today - timedelta(days=offsets[i + 1])),
                                 u[0], u[1], -d, balance,
                                 self.rng.choice(CONTROLLED_REASONS),
                                 self.rng.choice(STAFF_NAMES)))
        self.conn.executemany(
            "INSERT INTO controlled_log (id, item_id, occurred_at, user_id, "
            "username, change, balance_after, reason, witness) "
            "VALUES (?,?,?,?,?,?,?,?,?)", log_rows)
        self.n_controlled_log = len(log_rows)

    # ---- purchase orders -------------------------------------------------- #
    def gen_purchase_orders(self):
        """Emit purchase orders across the full approval + fulfillment lifecycle
        (draft -> pending_approval -> approved -> submitted -> ordered ->
        received, plus cancelled/rejected off-ramps). The six primary states are
        always present; chaos adds a few more. Approval/submission/order/receipt
        timestamps are backfilled in lifecycle order, and approved_by is a
        manager. A 'received' PO's lines are fully received (received_qty ==
        quantity); these rows record the PO only and do NOT mutate
        quantity_on_hand / item_lot, preserving the on-hand invariant."""
        users = self.conn.execute(
            "SELECT id, username FROM app_user WHERE username IN "
            "('manager','member') ORDER BY id").fetchall() or \
            self.conn.execute(
                "SELECT id, username FROM app_user ORDER BY id").fetchall()
        # the approver / certifying officer is a manager (fallback: first user)
        approver = next((u[0] for u in users if u[1] == "manager"), users[0][0])
        active_items = [it for it in self.items
                        if it["status"] == "active"] or self.items

        # how far each status has advanced through the lifecycle
        REACHED = {"draft": 0, "pending_approval": 1, "approved": 2,
                   "submitted": 3, "ordered": 4, "received": 5,
                   "cancelled": 1, "rejected": 2}
        APPROVER_NOTES = ["Approved -- within budget.",
                          "Approved for the genotyping pipeline.",
                          "OK to proceed; charge to the core grant."]
        REJECT_NOTES = ["Rejected -- use the existing stock first.",
                        "Rejected -- get a second quote."]

        extra_pool = ["submitted", "cancelled", "ordered", "received",
                      "pending_approval", "rejected"]
        n_extra = round(self.chaos * 4)
        plan = ["received", "ordered", "draft", "pending_approval",
                "approved", "submitted"] + \
            [self.rng.choice(extra_pool) for _ in range(n_extra)]

        # Funding source + expected arrival: any PO that has reached
        # 'ordered' or 'submitted' gets a fund_id (soft ref fund(id); fund
        # rows are always seeded 1..len(FUND_SPECS) by gen_funds, regardless
        # of call order -- no hard FK) and an expected_arrival date. The
        # FIRST such PO (deterministically po_id=2, the fixed "ordered" plan
        # entry) is forced past-due vs "today" so a late shipment is always
        # demonstrable; the rest get a plausible future arrival.
        seen_past_due_po = False

        po_rows, line_rows = [], []
        po_id = line_id = 0
        for status in plan:
            po_id += 1
            u = self.rng.choice(users)
            k = self.rng.randint(1, 3)
            line_items = self.rng.sample(active_items,
                                         min(k, len(active_items)))
            vendor = line_items[0]["vendor"]
            created = self.today - timedelta(days=self.rng.randint(5, 40))
            reached = REACHED[status]
            approved_at = submitted_at = ordered_at = received_at = None
            approved_by = approver_note = None
            t = created
            if reached >= 2 or status == "rejected":       # went through review
                t = t + timedelta(days=self.rng.randint(1, 2))
                if status == "rejected":
                    approved_by = approver
                    approver_note = self.rng.choice(REJECT_NOTES)
                else:
                    approved_at = t
                    approved_by = approver
                    approver_note = self.rng.choice(APPROVER_NOTES)
            if reached >= 3:                                # submitted+
                t = t + timedelta(days=self.rng.randint(1, 2))
                submitted_at = t
            if reached >= 4:                                # ordered+
                t = t + timedelta(days=self.rng.randint(1, 3))
                ordered_at = t
            if reached >= 5:                                # received
                received_at = t + timedelta(days=self.rng.randint(2, 7))
            fund_id = expected_arrival = None
            if status in ("ordered", "submitted"):
                fund_id = ((po_id - 1) % len(self.FUND_SPECS)) + 1
                anchor = ordered_at or submitted_at
                if not seen_past_due_po:
                    expected_arrival = iso(self.today - timedelta(days=2))
                    seen_past_due_po = True
                else:
                    expected_arrival = iso(anchor + timedelta(days=7))
            po_rows.append((
                po_id, vendor, status, u[0], self._stamp(created),
                approved_by, self._stamp(approved_at) if approved_at else None,
                approver_note,
                self._stamp(submitted_at) if submitted_at else None,
                self._stamp(ordered_at) if ordered_at else None,
                self._stamp(received_at) if received_at else None,
                expected_arrival, fund_id,
                None))
            for it in line_items:
                line_id += 1
                qty = self.rng.randint(1, 10)
                unit_cost = round(it["cost"] * self.rng.uniform(0.9, 1.1), 2)
                received_qty = qty if status == "received" else 0
                line_rows.append((line_id, po_id, it["item_id"], qty,
                                  unit_cost, received_qty))

        # A MEMBER-created requisition: an explicit draft PO owned by the member
        # (distinct from the manager-owned lifecycle POs above), awaiting the
        # member's own "request approval" action. Deterministic (no rng) so
        # same-seed runs stay identical and downstream generators are unshifted.
        member = next((u[0] for u in users if u[1] == "member"), users[0][0])
        po_id += 1
        member_po = po_id
        po_rows.append((
            member_po, active_items[0]["vendor"], "draft", member,
            f"{iso(self.today)} 09:30:00",
            None, None, None, None, None, None,
            None, None,
            "Member requisition -- bench consumables"))
        req_items = active_items[:2] or active_items[:1]
        for qty, it in zip((4, 2), req_items):
            line_id += 1
            line_rows.append((line_id, member_po, it["item_id"], qty,
                              round(it["cost"], 2), 0))

        self.conn.executemany(
            "INSERT INTO purchase_order (id, vendor, status, created_by, "
            "created_at, approved_by, approved_at, approver_note, submitted_at, "
            "ordered_at, received_at, expected_arrival, fund_id, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", po_rows)
        self.conn.executemany(
            "INSERT INTO po_line (id, po_id, item_id, quantity, unit_cost, "
            "received_qty) VALUES (?,?,?,?,?,?)", line_rows)
        self.n_purchase_orders = len(po_rows)
        self.n_po_lines = len(line_rows)
        self.po_received_ids = [r[0] for r in po_rows if r[2] == "received"]

    # ---- attached documents ---------------------------------------------- #
    def gen_documents(self):
        """Attach documents (SDS / CoA / invoice) to items, lots, and POs. SDS
        rows link each active item that carries a product SDS to that URL; CoA
        rows attach each lot that carries a CoA link; an invoice is attached to
        each received PO. Exactly one of item_id/lot_id/po_id is set per row."""
        uploader = next((u[0] for u in self.conn.execute(
            "SELECT id, username FROM app_user ORDER BY id").fetchall()), None)
        docs = []
        did = 0
        for it in self.items:
            if it["sds_url"] and it["status"] == "active":
                did += 1
                ts = self._stamp(self.today -
                                 timedelta(days=self.rng.randint(10, 60)))
                docs.append((did, it["item_id"], None, None, "sds",
                             f"{it['name']} SDS", it["sds_url"], None,
                             ts, uploader))
        for lot in self.lots:
            if lot.get("coa_url"):
                did += 1
                ts = self._stamp(lot["received"])
                docs.append((did, None, lot["id"], None, "coa",
                             f"{lot['lot_number']} CoA", lot["coa_url"], None,
                             ts, uploader))
        for po_id in getattr(self, "po_received_ids", []):
            did += 1
            ts = self._stamp(self.today -
                             timedelta(days=self.rng.randint(3, 20)))
            docs.append((did, None, None, po_id, "invoice",
                         f"Vendor invoice PO-{po_id}",
                         f"https://example-vendor.com/invoices/PO-{po_id}.pdf",
                         None, ts, uploader))
        self.conn.executemany(
            "INSERT INTO item_document (id, item_id, lot_id, po_id, kind, label, "
            "url, filename, uploaded_at, uploaded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", docs)
        self.n_item_document = len(docs)

    # ---- funds / budget burn-down ------------------------------------------ #
    # (name, sponsor, budget, start offset (days before today), end offset
    # (days from today)). Budgets/dates are fixed regardless of preset, like
    # the hand-written seed.sql equivalents.
    FUND_SPECS = [
        ("R01-NS118273", "NIH", 250000.0, 670, 1400),
        ("NSF-IOS-2145589", "NSF", 180000.0, 550, 540),
        ("Startup Fund -- PI Lab Launch", "internal", 50000.0, 920, 180),
    ]

    def gen_funds(self):
        rows = []
        for i, (name, sponsor, budget, start_off, end_off) in enumerate(
                self.FUND_SPECS, start=1):
            start = self.today - timedelta(days=start_off)
            end = self.today + timedelta(days=end_off)
            rows.append((i, name, sponsor, budget, iso(start), iso(end), None))
        self.conn.executemany(
            "INSERT INTO fund (id, name, sponsor, budget, start_date, "
            "end_date, note) VALUES (?,?,?,?,?,?,?)", rows)
        self.n_fund = len(rows)

    def gen_fund_charges(self):
        """Draw down each fund with a mix of received-PO pass-throughs,
        manual entries, and ticket-linked reagent draws. Received POs are
        spread round-robin across funds; manual + ticket charges then top
        each fund up to a target burn (the LAST fund's target is ~90%, so
        the burn-down bar always has one warn/danger example, and remaining
        never goes negative)."""
        funds = self.conn.execute(
            "SELECT id, budget FROM fund ORDER BY id").fetchall()
        if not funds:
            return
        users = self.conn.execute(
            "SELECT id, username FROM app_user ORDER BY id").fetchall()
        if not users:
            return
        charger = next((u[0] for u in users if u[1] == "manager"), users[0][0])
        po_totals = self.conn.execute(
            """SELECT po.id, po.vendor, SUM(pl.quantity * pl.unit_cost)
               FROM purchase_order po JOIN po_line pl ON pl.po_id = po.id
               WHERE po.status = 'received'
               GROUP BY po.id ORDER BY po.id""").fetchall()
        ticket_ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM ticket ORDER BY id").fetchall()]

        fund_ids = [f[0] for f in funds]
        budget_by_id = {f[0]: f[1] for f in funds}
        rows = []
        cid = 0

        def add(fund_id, amount, source_type, source_id, desc, day_offset):
            nonlocal cid
            cid += 1
            ts = self._stamp(self.today - timedelta(days=day_offset))
            rows.append((cid, fund_id, round(amount, 2), source_type,
                        source_id, desc, ts, charger))

        # received POs, spread round-robin across the funds
        for i, (po_id, vendor, total) in enumerate(po_totals):
            fund_id = fund_ids[i % len(fund_ids)]
            add(fund_id, total, "purchase_order", po_id,
                f"PO #{po_id} ({vendor})", 10 + i * 3)

        # manual + ticket charges top each fund up toward a target burn; the
        # last fund targets ~90% so the burn-down bar has a warn/danger case.
        for i, fund_id in enumerate(fund_ids):
            budget = budget_by_id[fund_id]
            already = sum(r[2] for r in rows if r[1] == fund_id)
            if already >= budget:
                continue  # a received PO alone already covers the target
            target_pct = 0.90 if i == len(fund_ids) - 1 else 0.15 + 0.10 * i
            remaining = max(0.0, budget * target_pct - already)
            add(fund_id, remaining * 0.55, "manual", None,
                "Personnel effort / core-facility fees", 20 + i * 4)
            add(fund_id, remaining * 0.35, "manual", None,
                "Reagent + consumables stock-up", 15 + i * 4)
            if ticket_ids:
                tkt = ticket_ids[i % len(ticket_ids)]
                add(fund_id, remaining * 0.10, "ticket", tkt,
                    f"Ticket #{tkt} reagent draw", 8 + i * 2)

        self.conn.executemany(
            "INSERT INTO fund_charge (id, fund_id, amount, source_type, "
            "source_id, description, charged_at, charged_by) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
        self.n_fund_charge = len(rows)

    # ---- orchestration ---------------------------------------------------- #
    def run(self, ensure_demo_users):
        self.gen_staff()
        ensure_demo_users(self.conn)   # after staff so app_user.staff_id FKs resolve
        self.gen_floors()              # before locations so floor_id=1 resolves
        self.gen_locations()
        self.gen_equipment()               # after locations: needs real node ids
        self.gen_equipment_reservations()  # after equipment + app_user
        self.gen_equipment_maintenance()   # after equipment
        self.gen_protocols()
        self.gen_animals()
        self.gen_inventory()
        self.gen_catalog()          # bundled vendor catalog + substitute groups
        self.gen_controlled()       # after inventory: flags items + fills register
        self.gen_lots()
        self.gen_containers()
        self.gen_storage_conflict()  # guarantee a co-located incompatible pair
        self.gen_kits()              # bill-of-materials reagent recipes
        self.gen_preparations()      # in-house mixes (PBS 1x, PFA, aCSF, ...) + batches
        self.gen_chores()            # recurring lab-maintenance chores + log
        self.gen_counts()            # closed cycle-count session (containers)
        self.gen_orders()
        self.gen_training()
        self.gen_usage_events()
        self.gen_settings()
        self.gen_task_templates()
        self.gen_tickets()          # after usage_events (continues its ids) + templates
        self.gen_audit_log()        # after tickets (audit mirrors ticket events)
        self.gen_purchase_orders()  # purchasing workflow rows
        self.gen_documents()        # after lots + POs: attach SDS/CoA/invoice docs
        self.gen_funds()
        self.gen_fund_charges()     # after purchase_orders + tickets resolve
        self.conn.commit()


# --------------------------------------------------------------------------- #
# verification + summary
# --------------------------------------------------------------------------- #
def assert_invariant(conn):
    """quantity_on_hand must equal SUM(item_lot.quantity) for every item."""
    bad = conn.execute(
        """SELECT i.item_id, i.quantity_on_hand,
                  COALESCE((SELECT SUM(quantity) FROM item_lot l
                            WHERE l.item_id = i.item_id), 0) AS lot_sum
           FROM inventory i
           WHERE i.quantity_on_hand <>
                 COALESCE((SELECT SUM(quantity) FROM item_lot l
                           WHERE l.item_id = i.item_id), 0)"""
    ).fetchall()
    if bad:
        raise AssertionError(
            "on_hand != SUM(item_lot.quantity) for items: " +
            ", ".join(f"#{r[0]} (on_hand={r[1]}, lots={r[2]})" for r in bad))


def print_summary(conn, today, preset, seed):
    def n(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    tables = ["staff", "protocols", "animals", "inventory", "item_lot",
              "container", "orders", "training", "usage_event",
              "floor", "location_node", "app_user",
              "task_template", "task_template_line", "ticket", "ticket_line",
              "audit_log", "app_setting", "vendor_catalog", "substitute_group",
              "item_document", "kit", "kit_line", "count_session", "count_line",
              "equipment", "equipment_reservation", "equipment_maintenance",
              "fund", "fund_charge",
              "preparation", "preparation_line", "preparation_batch",
              "chore", "chore_log"]
    print("\n" + "=" * 52)
    print("  Nimble Lab Manager -- synthetic data generated")
    print(f"  preset={preset}  seed={seed}  today={today}")
    print("=" * 52)
    print("  table                     rows")
    print("  " + "-" * 34)
    for t in tables:
        print(f"  {t:<24}{n('SELECT COUNT(*) FROM ' + t):>6}")

    t = today
    low = n("SELECT COUNT(*) FROM inventory WHERE quantity_on_hand <= reorder_threshold")
    stockout = n("SELECT COUNT(*) FROM inventory WHERE quantity_on_hand = 0")
    expired = n("SELECT COUNT(*) FROM item_lot WHERE expiry_date IS NOT NULL "
                "AND expiry_date < ?", (t,))
    expiring = n("SELECT COUNT(*) FROM item_lot WHERE expiry_date IS NOT NULL "
                 "AND expiry_date >= ? AND expiry_date <= date(?, '+30 day')", (t, t))
    misplaced = n("""SELECT COUNT(*) FROM container
                     WHERE status='in_use' AND expected_box_id IS NOT NULL
                       AND (box_id<>expected_box_id OR row<>expected_row
                            OR col<>expected_col)""")
    overdue_p = n("SELECT COUNT(*) FROM protocols WHERE renewal_due < ?", (t,))
    exp_train = n("SELECT COUNT(*) FROM training WHERE expires_date < ?", (t,))
    print("  " + "-" * 34)
    print("  alerts / demo signal")
    print(f"  {'low-stock items':<24}{low:>6}")
    print(f"  {'stockout items':<24}{stockout:>6}")
    print(f"  {'expired lots':<24}{expired:>6}")
    print(f"  {'expiring (<=30d) lots':<24}{expiring:>6}")
    print(f"  {'misplaced containers':<24}{misplaced:>6}")
    print(f"  {'overdue protocols':<24}{overdue_p:>6}")
    print(f"  {'expired training':<24}{exp_train:>6}")
    print("  " + "-" * 34)
    print("  inventory by category")
    cats = conn.execute(
        "SELECT category, COUNT(*) FROM inventory "
        "GROUP BY category ORDER BY COUNT(*) DESC, category").fetchall()
    for cat, ct in cats:
        print(f"  {cat:<24}{ct:>6}")
    with_sds = n("SELECT COUNT(*) FROM inventory WHERE sds_url IS NOT NULL")
    with_coa = n("SELECT COUNT(*) FROM item_lot WHERE coa_url IS NOT NULL")
    with_disp = n("SELECT COUNT(*) FROM inventory "
                  "WHERE disposal_instructions IS NOT NULL")
    print("  " + "-" * 34)
    print(f"  {'items with SDS link':<24}{with_sds:>6}")
    print(f"  {'lots with CoA link':<24}{with_coa:>6}")
    print(f"  {'items with disposal note':<24}{with_disp:>6}")
    print("  " + "-" * 34)
    print("  activity / v2 signal")
    print(f"  {'tickets':<24}{n('SELECT COUNT(*) FROM ticket'):>6}")
    print(f"  {'ticket lines':<24}{n('SELECT COUNT(*) FROM ticket_line'):>6}")
    print(f"  {'task templates':<24}{n('SELECT COUNT(*) FROM task_template'):>6}")
    print(f"  {'audit-log entries':<24}{n('SELECT COUNT(*) FROM audit_log'):>6}")
    deprecated = n("SELECT COUNT(*) FROM inventory WHERE status = ?",
                   ("deprecated",))
    print(f"  {'deprecated items':<24}{deprecated:>6}")
    print("  " + "-" * 34)
    print("  purchasing / controlled")
    print(f"  {'purchase orders':<24}{n('SELECT COUNT(*) FROM purchase_order'):>6}")
    print(f"  {'PO lines':<24}{n('SELECT COUNT(*) FROM po_line'):>6}")
    print(f"  {'controlled items':<24}"
          f"{n('SELECT COUNT(*) FROM inventory WHERE is_controlled=1'):>6}")
    print(f"  {'controlled-log entries':<24}{n('SELECT COUNT(*) FROM controlled_log'):>6}")
    print("  " + "-" * 34)
    print("  catalog / documents")
    print(f"  {'vendor catalog rows':<24}{n('SELECT COUNT(*) FROM vendor_catalog'):>6}")
    print(f"  {'substitute groups':<24}{n('SELECT COUNT(*) FROM substitute_group'):>6}")
    print(f"  {'item documents':<24}{n('SELECT COUNT(*) FROM item_document'):>6}")
    po_states = conn.execute(
        "SELECT status, COUNT(*) FROM purchase_order "
        "GROUP BY status ORDER BY status").fetchall()
    print(f"  {'PO states':<24}"
          f"{', '.join(f'{s}:{c}' for s, c in po_states):>6}")
    print("  " + "-" * 34)
    print("  kits / cycle counts")
    print(f"  {'kits':<24}{n('SELECT COUNT(*) FROM kit'):>6}")
    print(f"  {'kit lines':<24}{n('SELECT COUNT(*) FROM kit_line'):>6}")
    print(f"  {'count sessions':<24}{n('SELECT COUNT(*) FROM count_session'):>6}")
    print(f"  {'count lines':<24}{n('SELECT COUNT(*) FROM count_line'):>6}")
    count_missing = n("SELECT COUNT(*) FROM count_line WHERE status='missing'")
    print(f"  {'count lines missing':<24}{count_missing:>6}")
    print("  " + "-" * 34)
    print("  equipment / funds")
    print(f"  {'equipment':<24}{n('SELECT COUNT(*) FROM equipment'):>6}")
    past_due = n("SELECT COUNT(*) FROM equipment WHERE next_service_date < ?", (t,))
    due_soon = n("SELECT COUNT(*) FROM equipment WHERE next_service_date >= ? "
                 "AND next_service_date <= date(?, '+14 day')", (t, t))
    print(f"  {'equipment past-due service':<24}{past_due:>6}")
    print(f"  {'equipment due <=14d':<24}{due_soon:>6}")
    print(f"  {'equipment reservations':<24}"
          f"{n('SELECT COUNT(*) FROM equipment_reservation'):>6}")
    print(f"  {'equipment maintenance':<24}"
          f"{n('SELECT COUNT(*) FROM equipment_maintenance'):>6}")
    print(f"  {'funds':<24}{n('SELECT COUNT(*) FROM fund'):>6}")
    print(f"  {'fund charges':<24}{n('SELECT COUNT(*) FROM fund_charge'):>6}")
    fund_burn = conn.execute(
        """SELECT f.name, f.budget,
                  COALESCE((SELECT SUM(amount) FROM fund_charge fc
                            WHERE fc.fund_id = f.id), 0) AS spent
           FROM fund f ORDER BY f.id""").fetchall()
    for name, budget, spent in fund_burn:
        pct = (spent / budget * 100) if budget else 0
        print(f"  {name[:22]:<24}{pct:>5.1f}%")
    print("=" * 52)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_config(args):
    cfg = dict(PRESETS[args.preset])
    for key, val in (("items", args.items), ("freezers", args.freezers),
                     ("boxes_per_freezer", args.boxes_per_freezer),
                     ("days", args.days)):
        if val is not None:
            cfg[key] = val
    cfg["catalog"] = args.catalog
    cfg["molbio"] = args.molbio
    return cfg


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Fabricate a self-consistent lab world into a SQLite DB.")
    p.add_argument("--preset", choices=list(PRESETS), default="small")
    p.add_argument("--items", type=int, default=None)
    p.add_argument("--freezers", type=int, default=None)
    p.add_argument("--boxes-per-freezer", type=int, default=None,
                   dest="boxes_per_freezer")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--catalog", type=int, default=0,
                   help="synthesize N extra bulk vendor_catalog rows on top of "
                        "the fixed set (default 0; for stress-testing long "
                        "lists / search / pagination)")
    p.add_argument("--molbio", action="store_true",
                   help="seed the curated real molecular-biology catalog (enzymes, "
                        "kits, competent cells, buffers, media, antibodies)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--db", default=None, help="output DB path (default: lab.db in repo root)")
    p.add_argument("--force", action="store_true", help="rebuild if the DB exists")
    p.add_argument("--today", default=DEFAULT_TODAY,
                   help="anchor date YYYY-MM-DD for all relative dates")
    args = p.parse_args(argv)

    # locate repo files relative to this script so it stays portable
    root = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(root, "schema.sql")
    db_path = args.db or os.path.join(root, "lab.db")

    try:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    except ValueError:
        print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        return 2

    if os.path.exists(db_path):
        if not args.force:
            print(f"error: {db_path} already exists. Use --force to rebuild.",
                  file=sys.stderr)
            return 1
        os.remove(db_path)

    # import auth so generated DBs are loginable (adds pkg dir to path)
    sys.path.insert(0, root)
    import random

    from app import auth
    rng = random.Random(args.seed)
    cfg = build_config(args)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(schema_path, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        gen = Generator(conn, rng, cfg, today)
        gen.run(auth.ensure_demo_users)
        assert_invariant(conn)
        print_summary(conn, args.today, args.preset, args.seed)
    finally:
        conn.close()
    print(f"\nWrote {db_path}")
    print("Login with admin/admin, manager/manager, member/member, viewer/viewer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
