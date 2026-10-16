"""Snapdragon SoC part numbers to marketing names, Adreno GPU and Hexagon arch.

Only used to label results. What the device itself reports (Vulkan/OpenCL
device name, getprop, /sys/devices/soc0) always wins. Leave a field None
rather than guess.
"""

import re

SOCS = {
    "SM8450": ("Snapdragon 8 Gen 1", "Adreno 730", "v69"),
    "SM8475": ("Snapdragon 8+ Gen 1", "Adreno 730", "v69"),
    "SM8550": ("Snapdragon 8 Gen 2", "Adreno 740", "v73"),
    "SM8635": ("Snapdragon 8s Gen 3", "Adreno 735", None),
    "SM8650": ("Snapdragon 8 Gen 3", "Adreno 750", "v75"),
    "SM8735": ("Snapdragon 8s Gen 4", "Adreno 825", None),
    "SM8750": ("Snapdragon 8 Elite", "Adreno 830", "v79"),
    "SM8850": ("Snapdragon 8 Elite Gen 5", "Adreno 840", "v81"),
    "SM7550": ("Snapdragon 7 Gen 3", "Adreno 720", None),
    "SM7675": ("Snapdragon 7+ Gen 3", "Adreno 732", None),
    "X1E00": ("Snapdragon X Elite", "Adreno X1-85", "v73"),
    "X1P64": ("Snapdragon X Plus", "Adreno X1-85", "v73"),
    "X1P42": ("Snapdragon X Plus", "Adreno X1-45", "v73"),
    "X2E": ("Snapdragon X2 Elite", None, "v81"),
}

# Android board platform codenames (ro.board.platform / soc0 machine).
CODENAMES = {
    "taro": "SM8450",
    "kalama": "SM8550",
    "pineapple": "SM8650",
    "sun": "SM8750",
    "canoe": "SM8850",
    "cliffs": "SM8635",
    "crow": "SM7550",
    "volcano": "SM7675",
}


def normalize_part(text):
    """Find a Snapdragon part number in free text, e.g. 'SM8650', 'X1E78100'."""
    if not text:
        return None
    t = text.upper()
    m = re.search(r"\b(SM\d{4})", t)
    if m:
        return m.group(1)
    m = re.search(r"\b(X1[EP])-?(\d{2})-?(\d{3})", t)
    if m:
        return "%s%s%s" % m.groups()
    m = re.search(r"\b(X2E)-?(\d{2})-?(\d{3})", t)
    if m:
        return "%s%s%s" % m.groups()
    low = text.strip().lower()
    if low in CODENAMES:
        return CODENAMES[low]
    return None


def lookup(part):
    """Return (marketing_name, gpu, hexagon_arch) for a part number."""
    if not part:
        return (None, None, None)
    if part in SOCS:
        return SOCS[part]
    if part.startswith("X1E"):
        return SOCS["X1E00"]
    for prefix in ("X1P64", "X1P42", "X2E"):
        if part.startswith(prefix):
            return SOCS[prefix]
    return (None, None, None)
