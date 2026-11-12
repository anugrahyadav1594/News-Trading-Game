from decimal import Decimal
from typing import Any

INITIAL_INDIAN_STOCKS: list[dict[str, Any]] = [
    {
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries",
        "sector": "Energy, Retail and Telecommunications",
        "sub_sectors": ["Oil-to-Chemicals", "Telecommunications", "Organized Retail", "New Energy"],
        "description": (
            "Simulated tournament benchmark conglomerate spanning refining & petrochemicals, "
            "nationwide 5G digital/telecom services, organized consumer retail, and green hydrogen/solar manufacturing."
        ),
        "base_volatility": Decimal("0.0180"),
        "simulated_market_cap_cr": Decimal("1950000.00"),
        "simulated_pe_ratio": Decimal("26.50"),
        "factor_exposures": {
            "refining_margins": 0.85,
            "crude_oil_spike": -0.35,
            "telecom_arpu": 0.75,
            "retail_consumer_demand": 0.70,
            "green_energy_subsidy": 0.60,
            "windfall_energy_tax": -0.80,
            "spectrum_regulation": -0.55,
            "corporate_tax_cut": 0.45,
            "interest_rate_hike": -0.25,
            "usd_inr_depreciation": -0.20,
            "fii_inflows": 0.50,
            "geopolitical_supply_shock": -0.30,
            "domestic_capex_policy": 0.55,
        },
        "supply_chain_links": {"crude_imports": -0.35, "domestic_logistics": 0.30},
    },
    {
        "symbol": "ICICIBANK",
        "company_name": "ICICI Bank",
        "sector": "Banking and Financial Services",
        "sub_sectors": ["Private Sector Banking", "Retail Credit", "Corporate Lending", "Treasury"],
        "description": (
            "Simulated private-sector universal bank exposed to RBI monetary policy, system liquidity, "
            "retail/corporate credit growth, asset quality cycles, and capital-adequacy regulations."
        ),
        "base_volatility": Decimal("0.0190"),
        "simulated_market_cap_cr": Decimal("890000.00"),
        "simulated_pe_ratio": Decimal("19.20"),
        "factor_exposures": {
            "rbi_repo_hike": -0.30,
            "rbi_liquidity_easing": 0.75,
            "crr_slr_tightening": -0.70,
            "credit_growth": 0.85,
            "nim_expansion": 0.80,
            "npa_credit_stress": -0.90,
            "banking_regulation_tightening": -0.65,
            "corporate_tax_cut": 0.45,
            "fii_inflows": 0.65,
            "usd_inr_depreciation": -0.25,
            "sovereign_yield_spike": -0.45,
            "retail_consumer_demand": 0.40,
            "domestic_capex_policy": 0.50,
        },
        "supply_chain_links": {"auto_loan_demand": 0.25, "corporate_capex_borrowing": 0.45},
    },
    {
        "symbol": "TATAMOTORS",
        "company_name": "Tata Motors",
        "sector": "Automotive and Electric Vehicles",
        "sub_sectors": ["Electric Vehicles", "Commercial Vehicles", "Passenger Vehicles", "Global Luxury Auto"],
        "description": (
            "Simulated automotive & EV manufacturer sensitive to EV incentives, domestic commercial/passenger "
            "demand, international auto tariffs, battery/lithium & steel input costs, and auto financing rates."
        ),
        "base_volatility": Decimal("0.0240"),
        "simulated_market_cap_cr": Decimal("360000.00"),
        "simulated_pe_ratio": Decimal("14.80"),
        "factor_exposures": {
            "ev_subsidy_policy": 0.90,
            "auto_demand": 0.85,
            "export_import_tariff_hike": -0.80,
            "battery_lithium_cost_spike": -0.70,
            "steel_commodity_spike": -0.65,
            "crude_oil_spike": -0.40,
            "interest_rate_hike": -0.55,
            "rbi_repo_hike": -0.45,
            "emission_regulation_tightening": -0.45,
            "labour_dispute_risk": -0.60,
            "usd_inr_depreciation": -0.25,
            "retail_consumer_demand": 0.55,
            "domestic_capex_policy": 0.50,
        },
        "supply_chain_links": {"semiconductor_supply": 0.60, "steel_inputs": -0.65, "battery_cells": -0.70},
    },
    {
        "symbol": "SUNPHARMA",
        "company_name": "Sun Pharmaceutical Industries",
        "sector": "Pharmaceuticals and Healthcare",
        "sub_sectors": ["Specialty Generics", "US Formulations", "Domestic Formulations", "APIs"],
        "description": (
            "Simulated global specialty & generic pharmaceutical leader sensitive to USFDA inspections, "
            "drug approvals, patent litigation, domestic price controls, API supply chains, and USD export realizations."
        ),
        "base_volatility": Decimal("0.0175"),
        "simulated_market_cap_cr": Decimal("430000.00"),
        "simulated_pe_ratio": Decimal("33.40"),
        "factor_exposures": {
            "usfda_approval": 0.90,
            "usfda_compliance_issue": -0.90,
            "patent_exclusivity_win": 0.80,
            "healthcare_price_cap": -0.75,
            "api_supply_disruption": -0.65,
            "pharma_export_demand": 0.75,
            "usd_inr_depreciation": 0.55,
            "export_import_tariff_hike": -0.45,
            "interest_rate_hike": -0.10,
            "corporate_tax_cut": 0.35,
            "geopolitical_supply_shock": -0.25,
            "fii_inflows": 0.30,
        },
        "supply_chain_links": {"imported_api_intermediates": -0.55, "us_specialty_channel": 0.75},
    },
    {
        "symbol": "INFY",
        "company_name": "Infosys",
        "sector": "IT Services and Technology",
        "sub_sectors": ["Enterprise Cloud & AI", "BFSI Tech Consulting", "Digital Outsourcing"],
        "description": (
            "Simulated global IT services & AI consulting bellwether driven by US/European enterprise tech budgets, "
            "large deal signings, USD/INR exchange rates, US macro conditions, and skilled-visa policies."
        ),
        "base_volatility": Decimal("0.0210"),
        "simulated_market_cap_cr": Decimal("780000.00"),
        "simulated_pe_ratio": Decimal("27.90"),
        "factor_exposures": {
            "global_it_spending": 0.90,
            "ai_cloud_deal_momentum": 0.85,
            "us_recession_risk": -0.85,
            "usd_inr_depreciation": 0.70,
            "visa_immigration_restriction": -0.75,
            "cybersecurity_sla_incident": -0.70,
            "interest_rate_hike": -0.30,
            "corporate_tax_cut": 0.35,
            "fii_inflows": 0.45,
            "export_import_tariff_hike": -0.20,
        },
        "supply_chain_links": {"us_bfsi_clients": 0.80, "cloud_hyperscalers": 0.55},
    },
]
