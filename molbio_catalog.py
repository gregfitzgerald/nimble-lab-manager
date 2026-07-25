"""Curated real-world molecular-biology catalog for the chemical-database POC.

This is a hand-built list of the products a typical molecular-biology lab actually
buys -- polymerases, ligases, restriction enzymes, cloning/prep kits, competent
cells, ladders, common buffers/chemicals (with real CAS numbers + GHS hazards),
media, and antibiotics. Catalog numbers use each vendor's real product codes where
known; treat prices/pack sizes as representative.

generate_data.py imports MOLBIO_CATALOG to seed a realistic vendor_catalog (via the
--molbio flag) and REAL_CHEMICALS so procedurally-synthesized chemical rows carry
real chemical identities (name + CAS) rather than invented ones.

Each MOLBIO_CATALOG row:
  (product_name, vendor, catalog_number, category, pack_size, unit,
   list_price, cas_number, hazard_class)
category is one of the app's inventory categories: enzyme | reagent | chemical |
media | antibody | supply. hazard_class is comma-separated GHS keywords or None.
"""

MOLBIO_CATALOG = [
    # ---- Polymerases & PCR ----
    ("Taq DNA Polymerase", "NEB", "M0273S", "enzyme", "400 units", "vial", 62.00, None, None),
    ("Q5 High-Fidelity DNA Polymerase", "NEB", "M0491S", "enzyme", "100 units", "vial", 68.00, None, None),
    ("Phusion High-Fidelity DNA Polymerase", "Thermo Fisher", "F530S", "enzyme", "100 units", "vial", 130.00, None, None),
    ("OneTaq 2X Master Mix with Std Buffer", "NEB", "M0482S", "reagent", "100 rxn", "vial", 60.00, None, None),
    ("Q5 High-Fidelity 2X Master Mix", "NEB", "M0492S", "reagent", "100 rxn", "vial", 78.00, None, None),
    ("GoTaq Green Master Mix", "Promega", "M7122", "reagent", "100 rxn", "vial", 72.00, None, None),
    ("PowerUp SYBR Green Master Mix", "Applied Biosystems", "A25742", "reagent", "500 rxn", "vial", 210.00, None, None),
    ("TaqMan Fast Advanced Master Mix", "Applied Biosystems", "4444557", "reagent", "200 rxn", "vial", 245.00, None, None),
    ("dNTP Mix (10 mM each)", "NEB", "N0447S", "reagent", "8 x 250 uL", "pack", 58.00, None, None),
    # ---- Ligases, kinases, phosphatases ----
    ("T4 DNA Ligase", "NEB", "M0202S", "enzyme", "20000 units", "vial", 62.00, None, None),
    ("T4 Polynucleotide Kinase", "NEB", "M0201S", "enzyme", "500 units", "vial", 56.00, None, None),
    ("Quick Ligation Kit", "NEB", "M2200S", "reagent", "30 rxn", "kit", 66.00, None, None),
    ("Antarctic Phosphatase", "NEB", "M0289S", "enzyme", "1000 units", "vial", 62.00, None, None),
    ("Calf Intestinal Alkaline Phosphatase (CIP)", "NEB", "M0290S", "enzyme", "1000 units", "vial", 62.00, None, None),
    ("Gibson Assembly Master Mix", "NEB", "E2611S", "reagent", "10 rxn", "kit", 130.00, None, None),
    ("NEBuilder HiFi DNA Assembly Master Mix", "NEB", "E2621S", "reagent", "10 rxn", "kit", 145.00, None, None),
    # ---- Restriction enzymes ----
    ("EcoRI-HF", "NEB", "R3101S", "enzyme", "10000 units", "vial", 62.00, None, None),
    ("BamHI-HF", "NEB", "R3136S", "enzyme", "10000 units", "vial", 62.00, None, None),
    ("HindIII-HF", "NEB", "R3104S", "enzyme", "10000 units", "vial", 62.00, None, None),
    ("XhoI", "NEB", "R0146S", "enzyme", "5000 units", "vial", 62.00, None, None),
    ("NotI-HF", "NEB", "R3189S", "enzyme", "2500 units", "vial", 66.00, None, None),
    ("NdeI", "NEB", "R0111S", "enzyme", "4000 units", "vial", 62.00, None, None),
    ("DpnI", "NEB", "R0176S", "enzyme", "1000 units", "vial", 62.00, None, None),
    ("SalI-HF", "NEB", "R3138S", "enzyme", "2000 units", "vial", 62.00, None, None),
    # ---- Nucleic-acid enzymes ----
    ("DNase I (RNase-free)", "NEB", "M0303S", "enzyme", "1000 units", "vial", 68.00, None, None),
    ("RNase A", "Thermo Fisher", "EN0531", "enzyme", "50 mg", "vial", 74.00, None, None),
    ("Proteinase K", "Thermo Fisher", "EO0491", "enzyme", "100 mg", "vial", 96.00, None, None),
    ("M-MuLV Reverse Transcriptase", "NEB", "M0253S", "enzyme", "10000 units", "vial", 92.00, None, None),
    ("SuperScript IV Reverse Transcriptase", "Invitrogen", "18090010", "enzyme", "10000 units", "vial", 285.00, None, None),
    ("T7 RNA Polymerase", "NEB", "M0251S", "enzyme", "5000 units", "vial", 66.00, None, None),
    ("Exonuclease I (E. coli)", "NEB", "M0293S", "enzyme", "3000 units", "vial", 62.00, None, None),
    # ---- Ladders & loading dye ----
    ("100 bp DNA Ladder", "NEB", "N3231S", "reagent", "1250 uL", "vial", 74.00, None, None),
    ("1 kb DNA Ladder", "NEB", "N3232S", "reagent", "1000 uL", "vial", 74.00, None, None),
    ("Gel Loading Dye, Purple (6X)", "NEB", "B7024S", "reagent", "4 mL", "vial", 24.00, None, None),
    # ---- Competent cells ----
    ("NEB 5-alpha Competent E. coli (High Efficiency)", "NEB", "C2987H", "reagent", "20 x 50 uL", "pack", 96.00, None, None),
    ("BL21(DE3) Competent E. coli", "NEB", "C2527H", "reagent", "20 x 50 uL", "pack", 96.00, None, None),
    ("DH5-alpha Competent Cells", "Thermo Fisher", "18265017", "reagent", "20 x 50 uL", "pack", 92.00, None, None),
    # ---- Prep & quantitation kits ----
    ("QIAprep Spin Miniprep Kit", "QIAGEN", "27104", "reagent", "250 preps", "kit", 340.00, None, None),
    ("QIAquick Gel Extraction Kit", "QIAGEN", "28704", "reagent", "50 preps", "kit", 155.00, None, None),
    ("QIAquick PCR Purification Kit", "QIAGEN", "28104", "reagent", "50 preps", "kit", 150.00, None, None),
    ("RNeasy Mini Kit", "QIAGEN", "74104", "reagent", "50 preps", "kit", 310.00, None, None),
    ("DNeasy Blood & Tissue Kit", "QIAGEN", "69504", "reagent", "50 preps", "kit", 265.00, None, None),
    ("Monarch Plasmid Miniprep Kit", "NEB", "T1010S", "reagent", "50 preps", "kit", 78.00, None, None),
    ("Monarch DNA Gel Extraction Kit", "NEB", "T1020S", "reagent", "50 preps", "kit", 72.00, None, None),
    ("Qubit dsDNA HS Assay Kit", "Invitrogen", "Q32851", "reagent", "100 assays", "kit", 115.00, None, None),
    ("TRIzol Reagent", "Invitrogen", "15596026", "reagent", "100 mL", "bottle", 165.00, "108-95-2", "toxic,corrosive,irritant"),
    # ---- Common buffers / chemicals (real CAS) ----
    ("Tris base", "Sigma-Aldrich", "252859", "chemical", "1 kg", "bottle", 96.00, "77-86-1", "irritant"),
    ("Trizma hydrochloride (Tris-HCl)", "Sigma-Aldrich", "T3253", "chemical", "500 g", "bottle", 82.00, "1185-53-1", "irritant"),
    ("EDTA disodium salt dihydrate", "Sigma-Aldrich", "E5134", "chemical", "500 g", "bottle", 74.00, "6381-92-6", "irritant"),
    ("Sodium chloride", "Sigma-Aldrich", "S9888", "chemical", "1 kg", "bottle", 48.00, "7647-14-5", None),
    ("Sodium hydroxide pellets", "Sigma-Aldrich", "S8045", "chemical", "500 g", "bottle", 58.00, "1310-73-2", "corrosive"),
    ("Hydrochloric acid (37%)", "Sigma-Aldrich", "320331", "chemical", "2.5 L", "bottle", 62.00, "7647-01-0", "corrosive,toxic"),
    ("Acetic acid, glacial", "Sigma-Aldrich", "A6283", "chemical", "2.5 L", "bottle", 66.00, "64-19-7", "flammable,corrosive"),
    ("Sodium dodecyl sulfate (SDS)", "Sigma-Aldrich", "L3771", "chemical", "500 g", "bottle", 88.00, "151-21-3", "flammable,irritant,toxic"),
    ("DL-Dithiothreitol (DTT)", "Sigma-Aldrich", "43815", "chemical", "25 g", "bottle", 92.00, "3483-12-3", "irritant"),
    ("Glycerol", "Sigma-Aldrich", "G5516", "chemical", "1 L", "bottle", 54.00, "56-81-5", None),
    ("Dimethyl sulfoxide (DMSO)", "Sigma-Aldrich", "D8418", "chemical", "500 mL", "bottle", 60.00, "67-68-5", "irritant"),
    ("Ethanol, 200 proof", "Sigma-Aldrich", "E7023", "chemical", "1 L", "bottle", 78.00, "64-17-5", "flammable"),
    ("2-Propanol (isopropanol)", "Sigma-Aldrich", "I9516", "chemical", "1 L", "bottle", 58.00, "67-63-0", "flammable,irritant"),
    ("Methanol", "Sigma-Aldrich", "322415", "chemical", "1 L", "bottle", 52.00, "67-56-1", "flammable,toxic"),
    ("Chloroform", "Sigma-Aldrich", "C2432", "chemical", "1 L", "bottle", 72.00, "67-66-3", "toxic,irritant"),
    ("Phenol:Chloroform:Isoamyl alcohol (25:24:1)", "Sigma-Aldrich", "P3803", "chemical", "100 mL", "bottle", 96.00, "108-95-2", "toxic,corrosive"),
    ("2-Mercaptoethanol", "Sigma-Aldrich", "M3148", "chemical", "100 mL", "bottle", 64.00, "60-24-2", "toxic,flammable"),
    ("Ammonium persulfate (APS)", "Sigma-Aldrich", "A3678", "chemical", "100 g", "bottle", 56.00, "7727-54-0", "oxidizer,irritant"),
    ("TEMED", "Sigma-Aldrich", "T9281", "chemical", "50 mL", "bottle", 62.00, "110-18-9", "flammable,corrosive"),
    ("Acrylamide/Bis-acrylamide 40% (29:1)", "Sigma-Aldrich", "A7802", "chemical", "500 mL", "bottle", 110.00, "79-06-1", "toxic"),
    ("Agarose", "Sigma-Aldrich", "A9539", "chemical", "100 g", "bottle", 130.00, "9012-36-6", None),
    ("Boric acid", "Sigma-Aldrich", "B6768", "chemical", "1 kg", "bottle", 58.00, "10043-35-3", "toxic"),
    ("Magnesium chloride hexahydrate", "Sigma-Aldrich", "M2670", "chemical", "500 g", "bottle", 60.00, "7791-18-6", None),
    ("Potassium chloride", "Sigma-Aldrich", "P9333", "chemical", "1 kg", "bottle", 52.00, "7447-40-7", None),
    ("Sodium acetate", "Sigma-Aldrich", "S2889", "chemical", "500 g", "bottle", 56.00, "127-09-3", None),
    ("Guanidine thiocyanate", "Sigma-Aldrich", "G9277", "chemical", "500 g", "bottle", 118.00, "593-84-0", "toxic,irritant"),
    ("Formamide, deionized", "Sigma-Aldrich", "F9037", "chemical", "500 mL", "bottle", 88.00, "75-12-7", "toxic"),
    ("Ethidium bromide solution (10 mg/mL)", "Sigma-Aldrich", "E1510", "chemical", "10 mL", "bottle", 74.00, "1239-45-8", "toxic"),
    ("IPTG", "Sigma-Aldrich", "I6758", "chemical", "5 g", "bottle", 96.00, "367-93-1", "irritant"),
    ("X-gal", "Sigma-Aldrich", "B4252", "chemical", "1 g", "bottle", 88.00, "7240-90-6", "irritant"),
    ("HEPES", "Sigma-Aldrich", "H3375", "chemical", "250 g", "bottle", 92.00, "7365-45-9", None),
    ("Glycine", "Sigma-Aldrich", "G8898", "chemical", "1 kg", "bottle", 62.00, "56-40-6", None),
    ("Triton X-100", "Sigma-Aldrich", "X100", "chemical", "500 mL", "bottle", 64.00, "9002-93-1", "irritant"),
    ("Tween-20", "Sigma-Aldrich", "P9416", "chemical", "500 mL", "bottle", 58.00, "9005-64-5", None),
    ("Bovine Serum Albumin (BSA)", "Sigma-Aldrich", "A7906", "chemical", "100 g", "bottle", 190.00, "9048-46-8", None),
    ("Phenylmethylsulfonyl fluoride (PMSF)", "Sigma-Aldrich", "78830", "chemical", "5 g", "bottle", 84.00, "329-98-6", "toxic,corrosive"),
    # ---- Media & antibiotics ----
    ("LB Broth (Lennox)", "Sigma-Aldrich", "L3022", "media", "1 kg", "bottle", 96.00, None, None),
    ("LB Agar (Lennox)", "Sigma-Aldrich", "L2897", "media", "1 kg", "bottle", 110.00, None, None),
    ("SOC Medium", "Invitrogen", "15544034", "media", "100 mL", "bottle", 48.00, None, None),
    ("Agar, bacteriological", "Sigma-Aldrich", "A5306", "media", "500 g", "bottle", 130.00, "9002-18-0", None),
    ("Ampicillin sodium salt", "Sigma-Aldrich", "A9518", "chemical", "25 g", "bottle", 78.00, "69-52-3", "irritant"),
    ("Kanamycin sulfate", "Sigma-Aldrich", "60615", "chemical", "25 g", "bottle", 82.00, "25389-94-0", "toxic"),
    ("Chloramphenicol", "Sigma-Aldrich", "C0378", "chemical", "25 g", "bottle", 74.00, "56-75-7", "toxic"),
    ("Tetracycline hydrochloride", "Sigma-Aldrich", "T7660", "chemical", "25 g", "bottle", 80.00, "64-75-5", "irritant"),
    # ---- Antibodies ----
    ("Monoclonal Anti-beta-Actin (clone AC-15)", "Sigma-Aldrich", "A5316", "antibody", "200 uL", "vial", 385.00, None, None),
    ("Anti-GAPDH antibody (clone GA1R)", "Invitrogen", "MA5-15738", "antibody", "100 uL", "vial", 340.00, None, None),
    ("6x-His Tag Monoclonal Antibody (HIS.H8)", "Invitrogen", "MA1-21315", "antibody", "100 uL", "vial", 355.00, None, None),
    ("Goat anti-Mouse IgG (H+L), HRP", "Invitrogen", "31430", "antibody", "1 mL", "vial", 245.00, None, None),
    ("Goat anti-Rabbit IgG (H+L), HRP", "Invitrogen", "31460", "antibody", "1 mL", "vial", 245.00, None, None),
    # ---- Plasticware / consumables ----
    ("PCR Tubes 0.2 mL, thin-wall (1000)", "Thermo Fisher", "AB0620", "supply", "1000 tubes", "pack", 62.00, None, None),
    ("Filtered Pipette Tips, 200 uL (960)", "Thermo Fisher", "2069G", "supply", "960 tips", "pack", 96.00, None, None),
    ("Microcentrifuge Tubes 1.5 mL (500)", "Eppendorf", "022363204", "supply", "500 tubes", "pack", 78.00, None, None),
    ("Conical Centrifuge Tubes 50 mL (500)", "Corning", "352070", "supply", "500 tubes", "case", 210.00, None, None),
    ("Serological Pipettes 10 mL, sterile (200)", "Corning", "4488", "supply", "200 pipettes", "case", 96.00, None, None),
]

# Pool of real chemical identities (name, CAS, hazard) used to give procedurally
# synthesized chemical rows real identities instead of invented names.
REAL_CHEMICALS = [(r[0], r[7], r[8]) for r in MOLBIO_CATALOG if r[3] == "chemical"]
