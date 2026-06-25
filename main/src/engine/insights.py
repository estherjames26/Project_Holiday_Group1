# Builds the short pros/cons text shown on each destination card.

from __future__ import annotations

from typing import Any

from src.data.destinations import DESTINATIONS


def generate_destination_insights(dest: dict[str, Any], all_results: list[dict[str, Any]]) -> dict[str, Any]:
    pros: list[str] = []
    cons: list[str] = []
    bd = dest["breakdown"]

    if bd["weather"] >= 75:
        pros.append(f"Good weather fit ({dest['temp_max_c']}°C)")
    elif bd["weather"] < 50:
        cons.append(
            f"Weather is a bit off — {dest['wind_speed_ms']:.1f} m/s wind, {dest['cloudiness']}% cloud cover"
        )

    cheapest = min(all_results, key=lambda x: x["total_cost_usd"])
    if dest["id"] == cheapest["id"]:
        pros.append(f"Cheapest option in your list (${dest['total_cost_usd']:,.0f} for 7 nights)")
    elif dest["total_cost_usd"] > cheapest["total_cost_usd"] * 1.25:
        cons.append(
            f"About ${dest['total_cost_usd'] - cheapest['total_cost_usd']:,.0f} more than {cheapest['name']}"
        )

    costs = dest["costs"]
    if costs.get("airbnb_nightly_usd", 999) < costs.get("hotel_nightly_usd", 999) * 0.7:
        pros.append("Airbnb works out cheaper than hotels here")

    top_nightlife = max(all_results, key=lambda x: x["nightlife_total"])
    if dest["nightlife_total"] >= top_nightlife["nightlife_total"]:
        pros.append(f"Most bars/clubs nearby ({dest['nightlife_total']} within 5 km)")
    elif dest["nightlife_total"] < 5:
        cons.append("Not much nightlife — more of a daytime place")

    if bd["adventure"] >= 70:
        pros.append(f"Matches your interests: {', '.join(dest['adventure_tags'][:3])}")
    elif bd["adventure"] < 40:
        cons.append("Doesn't hit your activity tags as well as the others")

    rank = next(i + 1 for i, d in enumerate(all_results) if d["id"] == dest["id"])
    if rank == 1:
        verdict = "Top match for your settings."
    elif rank <= 3:
        verdict = f"#{rank} on your list — check cost vs nightlife before you decide."
    else:
        verdict = f"#{rank} — decent option, but a few places scored higher."

    return {
        "pros": pros[:4],
        "cons": cons[:3],
        "verdict": verdict,
        "rank": rank,
        "value_score": round(bd["cost"] * 0.5 + bd["nightlife"] * 0.3 + bd["adventure"] * 0.2, 1),
    }


def generate_portfolio_insights(results: list[dict[str, Any]], prefs: dict[str, Any]) -> list[str]:
    """Plain-text bullets only — no markdown, so Streamlit renders them cleanly."""
    if not results:
        return ["Nothing matched — try a bigger budget or wider temp range."]

    insights: list[str] = []
    top = results[0]
    budget_spread = max(r["total_cost_usd"] for r in results) - min(r["total_cost_usd"] for r in results)

    insights.append(f"{top['name']} comes out on top ({top['score']}/100) with your current weights.")

    if budget_spread > 500:
        cheapest = min(results, key=lambda x: x["total_cost_usd"])
        savings = top["total_cost_usd"] - cheapest["total_cost_usd"]
        if cheapest["id"] != top["id"] and savings > 50:
            insights.append(
                f"Prices range by about ${budget_spread:,.0f}. "
                f"{cheapest['name']} could save you around ${savings:,.0f} compared with {top['name']}."
            )
        elif cheapest["id"] == top["id"]:
            insights.append(
                f"Prices range by about ${budget_spread:,.0f} across your shortlist, "
                f"and {top['name']} is both the top pick and the cheapest."
            )

    best_weather = max(results, key=lambda x: x["breakdown"]["weather"])
    if best_weather["id"] != top["id"]:
        insights.append(
            f"{best_weather['name']} has the best weather score ({best_weather['breakdown']['weather']}/100) "
            f"if weather is your main thing."
        )

    best_nightlife = max(results, key=lambda x: x["nightlife_total"])
    if best_nightlife["id"] != top["id"] and best_nightlife["nightlife_total"] > top["nightlife_total"] + 2:
        insights.append(
            f"For nightlife, {best_nightlife['name']} has more venues "
            f"({best_nightlife['nightlife_total']} vs {top['nightlife_total']})."
        )

    filtered_count = len(DESTINATIONS) - len(results)
    if filtered_count > 0:
        insights.append(f"{filtered_count} destination(s) were filtered out by your current settings.")

    return insights
