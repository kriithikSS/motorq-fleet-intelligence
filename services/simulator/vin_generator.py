"""
VIN Generator — generates valid 17-character VINs.
Rules:
  - Positions 1-3: World Manufacturer Identifier (WMI)
  - Position 9: Check digit (computed)
  - Position 10: Model year
  - No I, O, or Q characters
  - Full ISO 3779 check-digit validation
"""

import random
import string
from typing import List

# Characters allowed in a VIN (no I, O, Q)
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

# Check-digit transliteration table
TRANSLITERATION: dict[str, int] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}

# Position weights (positions 1-17)
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

# Simulated WMIs for realistic OEM variety
WMIS = [
    "1HG",  # Honda USA
    "1FT",  # Ford USA
    "1G1",  # Chevrolet USA
    "1N4",  # Nissan USA
    "2T1",  # Toyota Canada
    "3VW",  # Volkswagen Mexico
    "JHM",  # Honda Japan
    "WVW",  # Volkswagen Germany
    "YV1",  # Volvo
    "1C4",  # Chrysler
    "KMH",  # Hyundai Korea
    "JTD",  # Toyota Japan
    "SAL",  # Land Rover UK
    "VF1",  # Renault France
    "ZAR",  # Alfa Romeo Italy
]

# Model year encoding (position 10)
YEAR_CHARS = {
    2020: "L", 2021: "M", 2022: "N", 2023: "P",
    2024: "R", 2025: "S", 2026: "T",
}


def _compute_check_digit(vin_without_check: str) -> str:
    """Compute the ISO 3779 check digit for positions 1-8 and 10-17."""
    total = 0
    chars = list(vin_without_check)
    # Positions in the VIN: indices 0-7 then 9-16 (skip index 8 = check digit)
    positions = list(range(0, 8)) + list(range(9, 17))
    for i, pos in enumerate(positions):
        weight = WEIGHTS[pos]
        val = TRANSLITERATION[chars[pos]]
        total += val * weight
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def generate_vin(year: int = 2024, oem_index: int | None = None) -> str:
    """Generate a single valid VIN."""
    if oem_index is None:
        oem_index = random.randint(0, len(WMIS) - 1)
    wmi = WMIS[oem_index % len(WMIS)]

    # VDS (positions 4-8) — vehicle descriptor section
    vds = "".join(random.choices(VIN_CHARS, k=5))

    # Position 9 (check digit) — placeholder
    check = "0"

    # Position 10 — model year
    year_char = YEAR_CHARS.get(year, "T")

    # Position 11 — plant code
    plant = random.choice(VIN_CHARS[:26])

    # Positions 12-17 — sequential number
    seq = "".join(random.choices(string.digits, k=6))

    # Assemble without check digit
    vin_parts = list(wmi + vds + check + year_char + plant + seq)

    # Compute and insert check digit
    vin_str = "".join(vin_parts)
    vin_parts[8] = _compute_check_digit(vin_str)
    vin = "".join(vin_parts)

    assert len(vin) == 17, f"VIN length error: {vin}"
    assert not any(c in vin for c in "IOQ"), f"Invalid char in VIN: {vin}"
    return vin


def validate_vin(vin: str) -> bool:
    """Validate a VIN string against ISO 3779 rules."""
    if len(vin) != 17:
        return False
    vin = vin.upper()
    if any(c in vin for c in "IOQ"):
        return False
    if not all(c in VIN_CHARS for c in vin):
        return False
    # Validate check digit
    check = _compute_check_digit(vin)
    return vin[8] == check


def generate_vin_batch(count: int, year: int = 2024) -> List[str]:
    """Generate a batch of unique VINs."""
    vins: set[str] = set()
    oem_idx = 0
    while len(vins) < count:
        vin = generate_vin(year=year, oem_index=oem_idx)
        vins.add(vin)
        oem_idx = (oem_idx + 1) % len(WMIS)
    return list(vins)


if __name__ == "__main__":
    # Quick sanity test
    for i in range(10):
        vin = generate_vin()
        valid = validate_vin(vin)
        print(f"VIN: {vin}  valid={valid}")

    batch = generate_vin_batch(100000)
    print(f"\nGenerated {len(batch)} unique VINs")
    print(f"Sample: {batch[:5]}")
