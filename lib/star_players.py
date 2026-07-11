"""
List of 'star players' - when one of these is substituted, we send a
special alert (instead of the regular substitution report).

This is a curated list of well-known players likely to appear in the
2026 World Cup knockout stage. Names are in English (as ESPN reports
them) so we can match against the parsed event data.
"""

# Star players - if any of these is substituted (in or out), we send
# a special alert. Match is case-insensitive on the surname.
STAR_PLAYERS = {
    # Tier 1 - global superstars (always alert)
    "Lionel Messi", "Cristiano Ronaldo", "Kylian Mbappe", "Erling Haaland",
    "Neymar", "Vinicius Junior", "Jude Bellingham", "Phil Foden",
    "Bukayo Saka", "Harry Kane", "Kevin De Bruyne", "Romelu Lukaku",
    "Robert Lewandowski", "Luka Modric", "Toni Kroos",

    # Tier 2 - well-known stars
    "Antoine Griezmann", "Olivier Giroud", "Ousmane Dembele",
    "Pedri", "Gavi", "Ferran Torres", "Lamine Yamal", "Mikel Merino",
    "Fabián Ruiz", "Álex Baena",
    "Brahim Díaz", "Achraf Hakimi", "Noussair Mazraoui",
    "Andreas Schjelderup", "Erling Haaland",
    "Martin Ødegaard", "Sander Berge",
    "Florian Wirtz", "Jamal Musiala", "Kai Havertz",
    "Federico Valverde", "Darwin Núñez",
    "Alphonso Davies", "Jonathan David",
    "Hirving Lozano", "Edson Álvarez",
    "Son Heung-min", "Lee Kang-in",
    "Takefusa Kubo", "Kaoru Mitoma",
    "Mohamed Salah", "Victor Osimhen", "Sadio Mané",
    "Riyad Mahrez",
}

# Surnames only (for fuzzy matching when ESPN uses a different first-name format)
_STAR_SURNAMES = set()
for name in STAR_PLAYERS:
    parts = name.split()
    if parts:
        _STAR_SURNAMES.add(parts[-1].lower())


def is_star_player(player_name):
    """Return True if the given player name matches a known star.
    Match is case-insensitive on either the full name or the surname."""
    if not player_name:
        return False
    name_lower = player_name.lower()
    # Check full name
    for star in STAR_PLAYERS:
        if star.lower() == name_lower:
            return True
    # Check surname
    parts = player_name.split()
    if parts:
        surname = parts[-1].lower()
        if surname in _STAR_SURNAMES:
            return True
    return False
