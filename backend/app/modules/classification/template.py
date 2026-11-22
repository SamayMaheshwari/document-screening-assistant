"""Template definition for the fictional UTO TD3 passport data page (UTO-TD3-v1).

Zones are expressed in the *rectified* canonical frame (1250x880). The same layout drives the
synthetic generator and the zone-based OCR, so it doubles as the 'document zone detection' step.
"""

TEMPLATE_ID = "UTO-TD3-v1"
CARD_W, CARD_H = 1250, 880

# value zones: name -> (x, y, w, h)
FIELD_ZONES = {
    "document_type": (400, 170, 120, 54),
    "issuer_code": (570, 170, 170, 54),
    "passport_number": (770, 170, 330, 54),
    "surname": (400, 252, 620, 54),
    "given_names": (400, 334, 620, 54),
    "nationality": (400, 416, 330, 54),
    "date_of_birth": (770, 416, 260, 54),
    "sex": (400, 498, 120, 54),
    "place_of_birth": (570, 498, 450, 54),
    "date_of_issue": (400, 580, 330, 54),
    "date_of_expiry": (770, 580, 260, 54),
    "authority": (400, 662, 330, 54),
}

FIELD_LABELS = {
    "document_type": "Type", "issuer_code": "Code of issuing State", "passport_number": "Passport No.",
    "surname": "Surname", "given_names": "Given names", "nationality": "Nationality",
    "date_of_birth": "Date of birth", "sex": "Sex", "place_of_birth": "Place of birth",
    "date_of_issue": "Date of issue", "date_of_expiry": "Date of expiry", "authority": "Authority",
}

PHOTO_ZONE = (60, 150, 300, 380)
STAMP_ZONE = (1040, 400, 180, 180)  # x, y, w, h (circular stamp bounding box)
HEADER_ZONE = (0, 0, 1250, 120)
MRZ_ZONE = (40, 735, 1170, 125)
MRZ_LINE_ZONES = [(40, 742, 1170, 56), (40, 800, 1170, 56)]

# zones forensics examines (name -> box)
FORENSIC_ZONES = {
    "portrait": PHOTO_ZONE,
    "surname": FIELD_ZONES["surname"],
    "given_names": FIELD_ZONES["given_names"],
    "date_of_birth": FIELD_ZONES["date_of_birth"],
    "passport_number": FIELD_ZONES["passport_number"],
    "dates_block": (400, 570, 640, 70),
    "stamp": STAMP_ZONE,
    "mrz": MRZ_ZONE,
}
