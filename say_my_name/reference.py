"""Reference data shared by generator and matcher (the kind of table a real
project takes from the INE municipality list or SAP's T005S regions)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class City:
    name: str
    province: str  # SAP REGIO for ES = 2-digit province code
    postcode_base: int  # postcodes are province + base..base+14
    aliases: tuple[str, ...] = field(default_factory=tuple)


CITIES: tuple[City, ...] = (
    City("Madrid", "28", 1, ("MADRID CAPITAL",)),
    City("Barcelona", "08", 1, ("BCN",)),
    City("Valencia", "46", 1, ("València",)),
    City("Sevilla", "41", 1),
    City("Zaragoza", "50", 1),
    City("Málaga", "29", 1),
    City("Murcia", "30", 1),
    City("Bilbao", "48", 1, ("Bilbo",)),
    City("Santa Cruz de Tenerife", "38", 1, ("S/C de Tenerife", "Sta. Cruz de Tenerife", "Santa Cruz de Tfe.")),
    City("San Cristóbal de La Laguna", "38", 200, ("La Laguna", "S.C. de La Laguna")),
    City("Las Palmas de Gran Canaria", "35", 1, ("Las Palmas de G.C.", "Las Palmas")),
    City("Valladolid", "47", 1),
    City("Vigo", "36", 200),
    City("Gijón", "33", 200, ("Xixón",)),
    City("Alicante", "03", 1, ("Alacant",)),
    City("Palma", "07", 1, ("Palma de Mallorca",)),
    City("A Coruña", "15", 1, ("La Coruña", "Coruña")),
    City("Vitoria-Gasteiz", "01", 1, ("Vitoria", "Gasteiz")),
    City("Pamplona", "31", 1, ("Iruña",)),
    City("Granada", "18", 1),
)
