"""KP planet significators (4-rule method).

Ported from KP_AI_astrologer/kp_core/analysis_engine.py — significator logic only,
without scoring or house-weight analysis.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from astro.kp_engine import KPEngine, PlanetNameUtils

Signification = Tuple[int, int]  # (house, rule)


class SignificatorCalculator:
    """Calculates KP significators for planets in a birth/event chart."""

    def __init__(self, engine: KPEngine):
        self.engine = engine
        self.planets = engine.get_all_planets_df()
        self.cusps = engine.get_all_cusps_df()
        self._precompute_chart_data()

    def _precompute_chart_data(self) -> None:
        self.planet_house_map = {
            planet: self._get_house_occupancy(info["longitude"])
            for planet, info in self.planets.iterrows()
        }
        self.house_occupants_map: Dict[int, List[str]] = defaultdict(list)
        for planet, house in self.planet_house_map.items():
            if house:
                self.house_occupants_map[house].append(planet)

    def _get_house_occupancy(self, longitude: float) -> int | None:
        for i in range(1, 13):
            cusp_start = self.cusps.loc[i]["longitude"]
            next_cusp_num = i % 12 + 1
            cusp_end = self.cusps.loc[next_cusp_num]["longitude"]

            normalized_lon = (longitude - cusp_start + 360) % 360
            normalized_end = (cusp_end - cusp_start + 360) % 360

            if normalized_lon < normalized_end:
                return i
        return None

    def get_significators(self, planet_name: str) -> List[Signification]:
        """4-step KP significator method, including Rahu/Ketu agent logic."""
        planet_name = PlanetNameUtils.standardize_for_index(planet_name)

        significations: List[Signification] = []
        planet_info = self.planets.loc[planet_name]
        planet_star_lord = planet_info["nl"]

        # Rule 1: planet in the star of occupants of a house.
        planet_star_lord_full = PlanetNameUtils.to_full_name(planet_star_lord)
        for house, occupants in self.house_occupants_map.items():
            for occupant in occupants:
                if planet_star_lord_full == occupant:
                    significations.append((house, 1))

        # Rule 2: occupants of a house.
        house_occupied = self.planet_house_map.get(planet_name)
        if house_occupied:
            significations.append((house_occupied, 2))

        # Rule 3: planet in the star of the lord of a vacant house.
        for house_num in range(1, 13):
            house_lord_short = self.cusps.loc[house_num]["sign_lord"]
            if planet_star_lord == house_lord_short:
                if not self.house_occupants_map.get(house_num):
                    significations.append((house_num, 3))

        # Rule 4: owners of a vacant house.
        planet_short_name = PlanetNameUtils.to_short_name(planet_name)
        for house_num in range(1, 13):
            house_lord_short = self.cusps.loc[house_num]["sign_lord"]
            if planet_short_name == house_lord_short:
                if not self.house_occupants_map.get(house_num):
                    significations.append((house_num, 4))

        # Rahu/Ketu: add agent significators via conjoint planets and sign lord.
        if planet_name in ("Rahu", "Ketu"):
            rahu_ketu_house = self.planet_house_map.get(planet_name)
            if rahu_ketu_house:
                conjoint_planets = [
                    p
                    for p in self.house_occupants_map.get(rahu_ketu_house, [])
                    if p != planet_name and p not in ("Rahu", "Ketu")
                ]

                agent_significations: List[Signification] = []
                for conjoint_planet in conjoint_planets:
                    try:
                        agent_significations.extend(self.get_significators(conjoint_planet))
                    except (KeyError, RecursionError):
                        pass

                sign_lord_short = planet_info["sign_lord"]
                try:
                    sign_lord_full = PlanetNameUtils.to_full_name(sign_lord_short)
                    if (
                        sign_lord_full not in ("Rahu", "Ketu")
                        and sign_lord_full not in conjoint_planets
                    ):
                        agent_significations.extend(self.get_significators(sign_lord_full))
                except (StopIteration, IndexError, KeyError, RecursionError):
                    pass

                significations.extend(agent_significations)

        return sorted(significations, key=lambda x: (x[1], x[0]))

    def _find_conjunction_partner(self, planet_name: str, orb: float = 6.0) -> str | None:
        if planet_name not in self.planets.index:
            return None

        planet_longitude = self.planets.loc[planet_name]["longitude"]
        for other_planet in self.planets.index:
            if other_planet == planet_name or other_planet in ("Rahu", "Ketu"):
                continue
            other_longitude = self.planets.loc[other_planet]["longitude"]
            diff = abs(planet_longitude - other_longitude)
            diff = min(diff, 360 - diff)
            if diff <= orb:
                return other_planet
        return None

    def _find_rahu_ketu_agent(self, node_name: str) -> str:
        if node_name not in self.planets.index:
            return "Sun"

        planet_info = self.planets.loc[node_name]
        conjunct_planet = self._find_conjunction_partner(node_name, orb=6.0)
        if conjunct_planet:
            return conjunct_planet

        nakshatra_lord_full = PlanetNameUtils.to_full_name(planet_info["nl"])
        if nakshatra_lord_full and nakshatra_lord_full not in ("Rahu", "Ketu"):
            return nakshatra_lord_full

        return PlanetNameUtils.to_full_name(planet_info["sign_lord"])

    def format_display(self, planet_name: str, significations: List[Signification]) -> str:
        """Human-readable significator string (matches original dashboard style)."""
        planet_name = PlanetNameUtils.standardize_for_index(planet_name)
        if planet_name in ("Rahu", "Ketu"):
            own = significations
            agent_name = self._find_rahu_ketu_agent(planet_name)
            agent = self.get_significators(agent_name)
            own_houses = ", ".join(str(h) for h, _ in own)
            agent_houses = ", ".join(str(h) for h, _ in agent)
            return f"Own: {own_houses} | Agent({agent_name}): {agent_houses}"
        return ", ".join(str(h) for h, _ in significations)

    def compute_all(self) -> Dict[str, dict]:
        """Return significators for every planet in the chart."""
        result: Dict[str, dict] = {}
        for planet in self.planets.index:
            sigs = self.get_significators(planet)
            result[planet] = {
                "significators": [{"house": h, "rule": r} for h, r in sigs],
                "significators_display": self.format_display(planet, sigs),
            }
        return result


def significators_for_engine(engine: KPEngine) -> Dict[str, dict]:
    """Convenience wrapper used by chart_service."""
    return SignificatorCalculator(engine).compute_all()
