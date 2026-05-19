#!/usr/bin/env python3
"""
Seed the database with fixture data for development.

Idempotent:
  - Users are matched by email; existing rows are skipped.
  - Organizations are matched by name; existing rows are reused so
    multiple Providers can share an Org across reseeds.
  - Providers are matched by (owner_id, org_id); existing rows are
    reused so PA fixtures can always point at a real Provider.
  - Provider-availability posts are matched by
    (kind='opening', owner_id, provider_id); existing
    rows are skipped.
  - Client-referral posts are matched by
    (kind='referral', owner_id, description); duplicates are
    skipped. Descriptions are verbose enough that this collision is
    essentially never a real-data conflict.

All fixture users share the password `password`.

Each post fixture declares `days_ago: int`; the seed overrides the
server-defaulted `created_at` to `now - days_ago` so the listings page
renders a spread of dates rather than a wall of identical timestamps.
"""

import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, TypedDict

# Local import to avoid circulars at module import time
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from src.auth_config import UserManager
from src.db import async_session_maker
from src.domain.logic.users.schema import UserCreate
from src.domain.models import (
    IntakeDetail,
    OpeningDetail,
    Organization,
    Post,
    Program,
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ReferralDetail,
    User,
)

SHARED_PASSWORD = "password"


class FixtureUser(TypedDict):
    email: str
    username: str
    is_superuser: bool


class FixtureOpening(TypedDict):
    owner_email: str
    days_ago: int
    provider: dict[str, Any]
    detail: dict[str, Any]


class FixtureReferral(TypedDict):
    owner_email: str
    days_ago: int
    detail: dict[str, Any]


FIXTURE_USERS: list[FixtureUser] = [
    {"email": "admin@example.com", "username": "admin", "is_superuser": True},
    {"email": "alice@example.com", "username": "alice", "is_superuser": False},
    {"email": "bob@example.com", "username": "bob", "is_superuser": False},
    # Additional fixture clinicians so posts span more authors — gives
    # the /posts feed a more realistic "many voices" feel and lets the
    # `posted_by` filter actually narrow things on dev data.
    {"email": "dr_chen@example.com", "username": "dr_chen", "is_superuser": False},
    {"email": "dr_patel@example.com", "username": "dr_patel", "is_superuser": False},
    {"email": "dr_rivera@example.com", "username": "dr_rivera", "is_superuser": False},
    {"email": "dr_okafor@example.com", "username": "dr_okafor", "is_superuser": False},
    {"email": "dr_jansen@example.com", "username": "dr_jansen", "is_superuser": False},
]


# Real-world canonical examples. Each fixture declares its Provider
# profile (practice + location + delivery format) alongside the PA
# announcement. The seed creates/reuses the Provider, then points the
# PA's `provider_id` at it. `days_ago` spreads `created_at` across the
# last ~6 months so the listing page shows date variance.
FIXTURE_OPENING: list[FixtureOpening] = [
    {
        "owner_email": "alice@example.com",
        "days_ago": 2,
        "provider": {
            "practice_name": "Katie Reeves, PhD",
            "org_type": "solo_practice",
            # Telehealth-only practice — sessions happen over video, but
            # the practice is legally registered at a real Bay Area
            # business address. The (in_person=no, virtual=yes) flags
            # carry the "telehealth-only" signal at the wire layer; the
            # address columns stay populated with a plausible value so
            # the providers list doesn't render a "(telehealth), CA
            # 00000" sentinel that reads like a placeholder bug.
            "location_city": "Mountain View",
            "location_state": "CA",
            "location_zip": "94040",
            "in_person_sessions": "no",
            "virtual_sessions": "yes",
            "accepts_out_of_network": False,
            "in_network_carriers": [],
            "sliding_scale": False,
            "cost": "$250 - $600 per session",
        },
        "detail": {
            "description": (
                "Solo private practice offering psychotherapy and medication "
                "management for older teens and transitional-age youth with "
                "ADHD, anxiety, depression, self-harm, and suicidality. "
                "Immediate availability for new patients. 25-minute med-"
                "management visits and 50-minute therapy sessions."
            ),
            "referral_instructions": "Contact via website to schedule an intake call.",
            "website": "https://katiereevesphd.com",
            "desired_times": [],
            "services": ["psychotherapy", "medication_management"],
            "settings": ["outpatient"],
            "treatment_modality": "Psychodynamic, control-mastery",
            "age_groups": [
                "adolescents_14_18",
                "young_adults_19_24",
                "adults_25_64",
            ],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "alice@example.com",
        "days_ago": 14,
        "provider": {
            "practice_name": "Camp BooHoo",
            "org_type": "other",
            "location_city": "Santa Clara",
            "location_state": "CA",
            # Venue (fairgrounds) has no specific ZIP — keep the
            # county-seat ZIP as a serviceable placeholder so the
            # Provider's NOT NULL constraint stays satisfied; the
            # narrative carries the real location info.
            "location_zip": "95050",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "accepts_out_of_network": False,
            "in_network_carriers": [],
            "sliding_scale": True,
            "cost": "$2,500 / session",
        },
        "detail": {
            "description": (
                "Therapeutic summer camp focused on social skills and emotion "
                "regulation for middle schoolers with ASD. Two 2-week cohorts "
                "(May 25 and Jun 18), M-F 9am-5pm at the Santa Clara County "
                "Fairgrounds."
            ),
            "referral_instructions": (
                "Visit our website to download the intake packet, then email "
                "campbooohoo@example.com to reserve a cohort spot."
            ),
            "website": "https://boohoocrybaby.com",
            "desired_times": [],
            "schedule_text": "May 25 & Jun 18 cohorts; 2-week sessions; M-F 9am–5pm",
            "services": ["group_therapy"],
            "settings": ["day_program"],
            "treatment_modality": "Social skills, emotion regulation",
            "age_groups": ["children_6_10", "preteens_11_13"],
            "languages": ["en", "es"],
            "genders": [],
        },
    },
    {
        "owner_email": "alice@example.com",
        "days_ago": 30,
        "provider": {
            "practice_name": "RISE IOP at CHC",
            "org_type": "clinic",
            "parent_org_name": "Children's Health Council",
            "location_city": "Palo Alto",
            "location_state": "CA",
            "location_zip": "94304",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            # Source says "no MediCal, please contact for carriers" — the
            # carrier list itself is in `referral_instructions`. `other`
            # stands in as the in-network signal.
            "accepts_out_of_network": True,
            "in_network_carriers": ["other"],
            "sliding_scale": True,
            "cost": "$4k/week",
        },
        "detail": {
            "description": (
                "RISE is a Comprehensive DBT intensive outpatient program for "
                "high school students with high acuity, including those with "
                "self-harm or suicidality at no immediate risk of harm to self "
                "or others. Two last-minute openings; new cohort starts May 11. "
                "M-F 8:30am-4:30pm."
            ),
            "referral_instructions": (
                "Please contact the program coordinator for intake details."
            ),
            "website": "https://chc.rise.org",
            "desired_times": [],
            "schedule_text": "M-F 8:30am–4:30pm; current cohort starts May 11",
            "services": [
                "psychotherapy",
                "medication_management",
                "group_therapy",
                "family_therapy",
            ],
            "settings": ["iop"],
            "treatment_modality": "Comprehensive DBT",
            "age_groups": ["adolescents_14_18"],
            "languages": ["en", "es"],
            "genders": [],
        },
    },
    {
        "owner_email": "dr_chen@example.com",
        "days_ago": 5,
        "provider": {
            "practice_name": "Lakeside Therapy Collective",
            "org_type": "group_practice",
            "location_city": "Seattle",
            "location_state": "WA",
            "location_zip": "98101",
            "in_person_sessions": "yes",
            "virtual_sessions": "yes",
            "accepts_out_of_network": True,
            "in_network_carriers": ["aetna", "anthem_bcbs", "cigna"],
            "sliding_scale": False,
            "cost": "$180–$220 / 50-min session",
        },
        "detail": {
            "description": (
                "Group practice of six licensed therapists. Currently accepting "
                "adults and couples for weekly psychotherapy — anxiety, "
                "depression, attachment, and life transitions. "
                "Mix of in-person and telehealth slots."
            ),
            "referral_instructions": (
                "Send a referral via our intake form or call (206) 555-0142."
            ),
            "website": "https://lakesidetherapy.example.com",
            "desired_times": [],
            "services": ["psychotherapy", "couples_therapy"],
            "settings": ["outpatient"],
            "treatment_modality": "Integrative, attachment-focused",
            "age_groups": ["adults_25_64", "older_adults_65_plus"],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "dr_patel@example.com",
        "days_ago": 1,
        "provider": {
            "practice_name": "Greenfield Psychiatry",
            "org_type": "solo_practice",
            "location_city": "Brooklyn",
            "location_state": "NY",
            "location_zip": "11215",
            "in_person_sessions": "yes",
            "virtual_sessions": "yes",
            "accepts_out_of_network": False,
            "in_network_carriers": [
                "aetna",
                "cigna",
                "optum",
                "united_healthcare",
                "anthem_bcbs",
            ],
            "sliding_scale": False,
            "cost": None,
        },
        "detail": {
            "description": (
                "Outpatient adult psychiatry — evaluations, medication "
                "management, and brief psychotherapy. Two new openings this "
                "month for in-network adults. Hindi and Gujarati spoken."
            ),
            "referral_instructions": (
                "Please send referrals via fax (718-555-0188) or our patient " "portal."
            ),
            "website": "https://greenfieldpsychiatry.example.com",
            "desired_times": [],
            "services": ["evaluation", "medication_management", "psychotherapy"],
            "settings": ["outpatient"],
            "treatment_modality": "Psychopharmacology, supportive therapy",
            "age_groups": ["young_adults_19_24", "adults_25_64"],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "dr_rivera@example.com",
        "days_ago": 9,
        "provider": {
            "practice_name": "Rivera Family Psychology",
            "org_type": "solo_practice",
            "location_city": "Austin",
            "location_state": "TX",
            "location_zip": "78704",
            "in_person_sessions": "no",
            "virtual_sessions": "yes",
            "accepts_out_of_network": True,
            "in_network_carriers": [],
            "sliding_scale": True,
            "cost": "$160 / 50 min · sliding scale to $75",
        },
        "detail": {
            "description": (
                "Bilingual (Spanish/English) child and family psychologist. "
                "Telehealth across Texas. Specializing in early childhood "
                "behavioral concerns, parent coaching, and trauma in young "
                "children."
            ),
            "referral_instructions": (
                "Email referrals to intake@riverafamilypsych.example.com — "
                "include a brief reason for referral and parent contact info."
            ),
            "website": "https://riverafamilypsych.example.com",
            "desired_times": [],
            "services": ["psychotherapy", "evaluation", "family_therapy"],
            "settings": ["outpatient"],
            "treatment_modality": "Parent–Child Interaction Therapy (PCIT)",
            "age_groups": ["children_0_5", "children_6_10", "preteens_11_13"],
            "languages": ["en", "es"],
            # Bilingual practice; explicitly inclusive of trans + non-
            # binary clients so families looking for affirming care see it.
            "genders": [
                "female",
                "male",
                "non_binary",
                "trans_female",
                "trans_male",
                "gender_diverse",
            ],
        },
    },
    {
        "owner_email": "dr_okafor@example.com",
        "days_ago": 21,
        "provider": {
            "practice_name": "Beacon Hill Family Therapy",
            "org_type": "group_practice",
            "location_city": "Boston",
            "location_state": "MA",
            "location_zip": "02114",
            "in_person_sessions": "yes",
            "virtual_sessions": "yes",
            "accepts_out_of_network": True,
            "in_network_carriers": [
                "aetna",
                "anthem_bcbs",
                "cigna",
                "optum",
                "tricare",
                "united_healthcare",
            ],
            "sliding_scale": True,
            "cost": "$200 / session, sliding scale available",
        },
        "detail": {
            "description": (
                "Family-systems practice serving adolescents and their "
                "families. Specialties: school refusal, divorce/coparenting, "
                "and emerging-adult separation. Most major insurance accepted."
            ),
            "referral_instructions": (
                "Phone intake preferred: (617) 555-0119. Voicemail returned "
                "within 24 business hours."
            ),
            "website": "https://beaconhillfamily.example.com",
            "desired_times": [],
            "services": ["family_therapy", "psychotherapy", "case_management"],
            "settings": ["outpatient"],
            "treatment_modality": "Structural and Bowenian family therapy",
            "age_groups": [
                "preteens_11_13",
                "adolescents_14_18",
                "young_adults_19_24",
                "adults_25_64",
            ],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "dr_jansen@example.com",
        "days_ago": 60,
        "provider": {
            "practice_name": "Mountainview Residential",
            "org_type": "clinic",
            "location_city": "Boulder",
            "location_state": "CO",
            "location_zip": "80302",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            # Insurance posture: program negotiates rates case-by-case.
            # `please_contact` would be the right CHECK value if we had
            # one on Provider; the model uses booleans, so we encode
            # the same intent as "self-pay only" + cost text.
            "accepts_out_of_network": True,
            "in_network_carriers": [],
            "sliding_scale": False,
            "cost": "Please contact for rate sheet",
        },
        "detail": {
            "description": (
                "30- and 60-day residential program for adolescents with "
                "co-occurring eating disorders and mood disorders. "
                "Intentionally small (12 beds); structured milieu with "
                "individual, group, and family therapy."
            ),
            "referral_instructions": (
                "Admissions team handles all clinical inquiries. Call "
                "(303) 555-0177 ext. 2 for an admissions clinician."
            ),
            "website": "https://mountainviewres.example.com",
            "desired_times": [],
            "schedule_text": "Rolling admissions; 30- and 60-day tracks",
            "services": [
                "psychotherapy",
                "medication_management",
                "group_therapy",
                "family_therapy",
            ],
            "settings": ["residential"],
            "treatment_modality": "Enhanced CBT-E for eating disorders",
            "age_groups": ["adolescents_14_18"],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "dr_chen@example.com",
        "days_ago": 45,
        "provider": {
            "practice_name": "Cascade PHP",
            "org_type": "clinic",
            "parent_org_name": "Cascade Health Network",
            "location_city": "Tacoma",
            "location_state": "WA",
            "location_zip": "98402",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "accepts_out_of_network": True,
            "in_network_carriers": [
                "aetna",
                "anthem_bcbs",
                "kaiser",
                "medicaid",
                "optum",
            ],
            "sliding_scale": False,
            "cost": None,
        },
        "detail": {
            "description": (
                "Adult partial-hospitalization program — 5 days/week, 6 hours/day. "
                "DBT skills, process group, individual therapy, and med "
                "management for mood, anxiety, and trauma-related conditions."
            ),
            "referral_instructions": (
                "Self-referrals and clinician referrals both welcome. Online "
                "intake form on website routes to admissions same-day."
            ),
            "website": "https://cascadephp.example.com",
            "desired_times": [],
            "schedule_text": "M-F 9am–3pm; 4-6 week average length of stay",
            "services": [
                "psychotherapy",
                "medication_management",
                "group_therapy",
            ],
            "settings": ["php"],
            "treatment_modality": "DBT-informed PHP",
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            "genders": [],
        },
    },
    {
        "owner_email": "bob@example.com",
        "days_ago": 110,
        "provider": {
            "practice_name": "North Loop Counseling",
            "org_type": "group_practice",
            "location_city": "Minneapolis",
            "location_state": "MN",
            "location_zip": "55401",
            "in_person_sessions": "yes",
            "virtual_sessions": "yes",
            "accepts_out_of_network": False,
            "in_network_carriers": ["anthem_bcbs", "medicaid", "united_healthcare"],
            "sliding_scale": True,
            "cost": "$150 / session · sliding to $40",
        },
        "detail": {
            "description": (
                "Solo LMFT practice. Currently has one Tuesday evening slot "
                "open for an adult or couple. Strong fit for ambivalence in "
                "relationships, attachment ruptures, and identity work."
            ),
            "referral_instructions": (
                "Text the practice line at (612) 555-0203 with a brief intro "
                "and I'll respond within 2 business days."
            ),
            "website": None,
            "desired_times": [
                "tuesday_pm",
            ],
            "services": ["psychotherapy", "couples_therapy"],
            "settings": ["outpatient"],
            "treatment_modality": "AEDP, IFS",
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            # Solo LMFT doing identity work — queer-affirming explicit so
            # LGBTQ+ adults and couples see the signal at scan distance.
            "genders": [
                "female",
                "male",
                "non_binary",
                "trans_female",
                "trans_male",
                "gender_diverse",
            ],
        },
    },
]


# Client-referral fixtures. Each is a clinician referring out one of
# their clients — the description is the part a reader scans on the
# listings page. Spread across states, age bands, insurance postures,
# and service needs so the /posts filters actually narrow on real data.
FIXTURE_REFERRAL: list[FixtureReferral] = [
    {
        "owner_email": "bob@example.com",
        "days_ago": 0,
        "detail": {
            "location_city": "Seattle",
            "location_state": "WA",
            "location_zip": "98109",
            "location_in_person": "yes",
            "location_virtual": "yes",
            "desired_times": ["wednesday_pm", "thursday_pm"],
            "age_groups": ["adolescents_14_18"],
            "languages": ["en"],
            "description": (
                "Looking for a trauma-focused therapist for a 14-year-old "
                "(she/her) with complex PTSD and emerging self-injury. Mom is "
                "engaged and on board. Aetna in-network strongly preferred; "
                "family is open to telehealth if needed."
            ),
            "services": ["psychotherapy"],
            "treatment_modality": "TF-CBT or EMDR preferred",
            "network_preference": "in_network_required",
            "gender": "female",
        },
    },
    {
        "owner_email": "dr_chen@example.com",
        "days_ago": 3,
        "detail": {
            "location_city": "Tacoma",
            "location_state": "WA",
            "location_zip": "98402",
            "location_in_person": "yes",
            "location_virtual": "no",
            "desired_times": ["monday_am", "wednesday_am"],
            "age_groups": ["children_6_10"],
            "languages": ["en", "es"],
            "description": (
                "Seeking a Spanish-speaking child psychologist for a 7yo with "
                "selective mutism. Family lives in Tacoma; in-person required. "
                "Mom has Medicaid (Apple Health). Parent coaching component "
                "important — family is open to PCIT."
            ),
            "services": ["psychotherapy", "evaluation"],
            "treatment_modality": "PCIT or behavior-based",
            "network_preference": "in_network_required",
            # 7yo with selective mutism — gender not specified in the
            # referring clinician's description.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "dr_patel@example.com",
        "days_ago": 6,
        "detail": {
            "location_city": "Brooklyn",
            "location_state": "NY",
            "location_zip": "11201",
            "location_in_person": "yes",
            "location_virtual": "yes",
            "desired_times": [
                "monday_pm",
                "tuesday_pm",
                "wednesday_pm",
            ],
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            "description": (
                "Adult patient (he/him, 38) with treatment-resistant depression "
                "and longstanding alcohol use. Currently on lithium augmentation. "
                "Looking for a DBT-trained therapist who is comfortable holding "
                "a long-term frame. Out-of-network OK; he can pay $150–200."
            ),
            "services": ["psychotherapy"],
            "treatment_modality": "DBT or DBT-informed",
            "network_preference": "in_network_preferred",
            "gender": "male",
        },
    },
    {
        "owner_email": "dr_rivera@example.com",
        "days_ago": 11,
        "detail": {
            "location_city": "Austin",
            "location_state": "TX",
            "location_zip": "78704",
            "location_in_person": "no",
            "location_virtual": "yes",
            "desired_times": ["saturday_am", "sunday_am"],
            "age_groups": ["young_adults_19_24"],
            "languages": ["en", "es"],
            "description": (
                "20yo college student (she/they) reaching out for support around "
                "gender identity and family conflict. Family is Spanish-speaking "
                "and not yet involved. Wants a queer-affirming, Spanish-fluent "
                "therapist; telehealth so they can do sessions from dorm."
            ),
            "services": ["psychotherapy"],
            "treatment_modality": None,
            "network_preference": "no_preference",
            # 20yo (she/they) doing gender-identity work — the queer-
            # affirming, Spanish-fluent ask drives the gender_diverse
            # signal so trans-affirming providers surface as matches.
            "gender": "gender_diverse",
        },
    },
    {
        "owner_email": "dr_okafor@example.com",
        "days_ago": 18,
        "detail": {
            "location_city": "Cambridge",
            "location_state": "MA",
            "location_zip": "02139",
            "location_in_person": "yes",
            "location_virtual": "no",
            "desired_times": [],
            "age_groups": ["preteens_11_13"],
            "languages": ["en"],
            "description": (
                "Looking for an evaluator (psychoeducational or "
                "neuropsychological) for an 11yo with longstanding attention "
                "and reading concerns. School is requesting a recent eval to "
                "update the IEP. Family has BCBS PPO."
            ),
            "services": ["evaluation"],
            "treatment_modality": None,
            "network_preference": "in_network_required",
            # 11yo — gender not stated by the referring clinician.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "alice@example.com",
        "days_ago": 25,
        "detail": {
            "location_city": "Oakland",
            "location_state": "CA",
            "location_zip": "94609",
            "location_in_person": "yes",
            "location_virtual": "yes",
            "desired_times": [
                "monday_pm",
                "tuesday_pm",
                "thursday_pm",
            ],
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            "description": (
                "Couple in their early 30s seeking couples therapy. Recent "
                "relational rupture (infidelity disclosed 6 weeks ago) and "
                "both partners are motivated to do the work. Prefer a Bay-Area "
                "therapist trained in EFT or Gottman."
            ),
            "services": ["couples_therapy"],
            "treatment_modality": "EFT or Gottman",
            "network_preference": "in_network_preferred",
            # Couple — the gender field models a single client; for
            # couples-therapy referrals the referrer typically leaves
            # it unspecified.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "dr_jansen@example.com",
        "days_ago": 33,
        "detail": {
            "location_city": "Denver",
            "location_state": "CO",
            "location_zip": "80205",
            "location_in_person": "yes",
            "location_virtual": "no",
            "desired_times": [],
            "age_groups": ["adolescents_14_18"],
            "languages": ["en"],
            "description": (
                "Stepping down a 17yo from our residential program — needs a "
                "twice-weekly outpatient psychiatrist for medication management "
                "and an outpatient DBT therapist to continue skills. Family is "
                "fully invested. Kaiser Colorado."
            ),
            "services": ["medication_management", "psychotherapy"],
            "treatment_modality": "DBT",
            "network_preference": "in_network_required",
            # 17yo stepping down from residential — gender unstated by
            # the referring clinician on the wire.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "bob@example.com",
        "days_ago": 40,
        "detail": {
            "location_city": "Minneapolis",
            "location_state": "MN",
            "location_zip": "55403",
            "location_in_person": "yes",
            "location_virtual": "yes",
            "desired_times": ["friday_am"],
            "age_groups": ["older_adults_65_plus"],
            "languages": ["en"],
            "description": (
                "72yo widow referred by her PCP for late-life depression "
                "following her husband's death 11 months ago. Strong fit for a "
                "geriatric-informed therapist. Medicare; willing to travel "
                "within the Twin Cities."
            ),
            "services": ["psychotherapy"],
            "treatment_modality": None,
            "network_preference": "in_network_required",
            "gender": "female",
        },
    },
    {
        "owner_email": "dr_chen@example.com",
        "days_ago": 55,
        "detail": {
            "location_city": "Seattle",
            "location_state": "WA",
            "location_zip": "98115",
            "location_in_person": "no",
            "location_virtual": "yes",
            "desired_times": ["wednesday_pm", "thursday_pm"],
            "age_groups": ["children_0_5", "children_6_10"],
            "languages": ["en"],
            "description": (
                "Parents of a 5yo with newly identified autism are looking for "
                "a parent-coaching clinician (ESDM or similar). Want telehealth "
                "so both parents can join sessions from work. Premera BCBS."
            ),
            "services": ["family_therapy", "case_management"],
            "treatment_modality": "ESDM or PCIT",
            "network_preference": "in_network_required",
            # 5yo with autism — gender not stated by referring family.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "dr_patel@example.com",
        "days_ago": 72,
        "detail": {
            "location_city": "Queens",
            "location_state": "NY",
            "location_zip": "11375",
            "location_in_person": "yes",
            "location_virtual": "yes",
            "desired_times": [],
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            "description": (
                "Adult patient with bipolar I, currently stable on lithium and "
                "lurasidone. Needs a long-term outpatient psychiatrist as "
                "primary care moves out of NYC. Open to in-person or telehealth. "
                "Aetna PPO."
            ),
            "services": ["medication_management"],
            "treatment_modality": None,
            "network_preference": "in_network_required",
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "dr_okafor@example.com",
        "days_ago": 95,
        "detail": {
            "location_city": "Boston",
            "location_state": "MA",
            "location_zip": "02118",
            "location_in_person": "yes",
            "location_virtual": "no",
            "desired_times": [
                "monday_am",
                "tuesday_am",
                "wednesday_am",
                "thursday_am",
                "friday_am",
            ],
            "age_groups": ["young_adults_19_24", "adults_25_64"],
            "languages": ["en"],
            "description": (
                "Group practice has openings for IOP-level adults stepping "
                "down from inpatient. Need community-based clinicians who can "
                "see daily for 3-4 weeks while we coordinate care. Will "
                "accept any major insurance — please contact for specifics."
            ),
            "services": ["case_management"],
            "treatment_modality": None,
            "network_preference": "no_preference",
            # Multi-client referral (the group practice has openings,
            # not a single named client) — gender doesn't apply.
            "gender": "prefer_not_to_say",
        },
    },
    {
        "owner_email": "alice@example.com",
        "days_ago": 165,
        "detail": {
            "location_city": "San Francisco",
            "location_state": "CA",
            "location_zip": "94110",
            "location_in_person": "no",
            "location_virtual": "yes",
            "desired_times": ["saturday_pm"],
            "age_groups": ["adults_25_64"],
            "languages": ["en"],
            "description": (
                "Tech-industry client (mid-30s, he/him) with longstanding "
                "social anxiety and recent depression. Hours are unpredictable. "
                "Weekend availability and telehealth are non-negotiable. "
                "Self-pay; budget is generous."
            ),
            "services": ["psychotherapy"],
            "treatment_modality": "CBT or ACT",
            "network_preference": "no_preference",
            "gender": "male",
        },
    },
]


# Standalone Organizations seeded WITHOUT a Provider attached — used today
# for hierarchy roots (a health_system whose Provider rows live under
# child clinic Orgs, e.g. Children's Health Council → "RISE IOP at CHC").
# Provider fixtures reference these by name via `parent_org_name`.
class FixtureStandaloneOrg(TypedDict):
    owner_email: str
    name: str
    type: str


FIXTURE_STANDALONE_ORGS: list[FixtureStandaloneOrg] = [
    {
        "owner_email": "alice@example.com",
        "name": "Children's Health Council",
        "type": "health_system",
    },
    {
        "owner_email": "dr_chen@example.com",
        "name": "Cascade Health Network",
        "type": "health_system",
    },
]


def _shift_created_at(post: Post, days_ago: int) -> None:
    """Override the `server_default=func.now()` on `Post.created_at` with
    a deterministic offset so the listings feed shows a spread of dates.
    Set before the row is flushed so the INSERT carries our value, not
    the server clock.
    """
    post.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)


async def seed_users() -> tuple[int, int]:
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)

        for fixture in FIXTURE_USERS:
            existing = await session.execute(
                select(User).where(User.email == fixture["email"])
            )
            if existing.scalar_one_or_none() is not None:
                print(f"⏭️  user {fixture['email']} already exists, skipping")
                skipped += 1
                continue

            user_create = UserCreate(
                email=fixture["email"],
                password=SHARED_PASSWORD,
                username=fixture["username"],
                is_superuser=fixture["is_superuser"],
                is_verified=True,
            )
            user = await manager.create(user_create, safe=False)
            print(
                f"✅ Created user {user.email} "
                f"(username={fixture['username']}, superuser={fixture['is_superuser']})"
            )
            created += 1

        await session.commit()

    return created, skipped


async def seed_standalone_orgs() -> tuple[int, int]:
    """Seed Organizations that exist independent of any Provider. Used
    today for hierarchy roots (a health_system Org whose child clinics
    each carry their own Providers). Idempotent on `name`.

    Runs BEFORE `seed_opening` because Provider fixtures may declare a
    `parent_org_name` that needs to resolve to a row here.
    """
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_STANDALONE_ORGS:
            existing = await session.execute(
                select(Organization).where(Organization.name == fixture["name"])
            )
            if existing.scalar_one_or_none() is not None:
                print(f"⏭️  org '{fixture['name']}' already exists, skipping")
                skipped += 1
                continue
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  org '{fixture['name']}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue
            org = Organization(
                id=uuid.uuid4(),
                name=fixture["name"],
                type=fixture["type"],
                owner_id=owner.id,
            )
            org.root_org_id = org.id
            session.add(org)
            print(f"✅ Created standalone org '{fixture['name']}' ({fixture['type']})")
            created += 1
        await session.commit()

    return created, skipped


async def seed_opening() -> tuple[int, int]:
    created = 0
    skipped = 0
    providers_created = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_OPENING:
            # The fixture declares `practice_name` as a convenience key
            # for the seeded Organization's name — it is NOT a column on
            # Provider. Strip it before splatting the fixture dict into
            # `Provider(**...)`.
            provider_fields = dict(fixture["provider"])
            practice_name = provider_fields.pop("practice_name")
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  PA post '{practice_name}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            # Find-or-create the Organization keyed on the fixture's
            # practice_name — the Org's `name` is the practice's display
            # name. The fixture optionally declares `org_type` (default
            # `solo_practice`) and `parent_org_name` (default None, i.e.
            # the Org is a root). When a parent name is set, the parent
            # must already be seeded — `seed_standalone_orgs()` runs
            # before this function for that reason.
            org_type = provider_fields.pop("org_type", "solo_practice")
            parent_org_name = provider_fields.pop("parent_org_name", None)
            org_result = await session.execute(
                select(Organization).where(Organization.name == practice_name)
            )
            org = org_result.scalar_one_or_none()
            if org is None:
                parent_org_id = None
                root_org_id = None
                if parent_org_name:
                    parent_result = await session.execute(
                        select(Organization).where(Organization.name == parent_org_name)
                    )
                    parent = parent_result.scalar_one_or_none()
                    if parent is None:
                        print(
                            f"⚠️  PA post '{practice_name}': "
                            f"parent org '{parent_org_name}' not found, "
                            f"creating as root instead"
                        )
                    else:
                        parent_org_id = parent.id
                        root_org_id = parent.root_org_id or parent.id
                org = Organization(
                    id=uuid.uuid4(),
                    name=practice_name,
                    type=org_type,
                    owner_id=owner.id,
                    parent_org_id=parent_org_id,
                )
                org.root_org_id = root_org_id or org.id
                session.add(org)
                await session.flush()

            # Find-or-create the Provider for (owner_id, org_id).
            # Reusing across reseeds keeps the FK stable.
            provider_result = await session.execute(
                select(Provider).where(
                    Provider.owner_id == owner.id,
                    Provider.org_id == org.id,
                )
            )
            provider = provider_result.scalar_one_or_none()
            if provider is None:
                provider = Provider(owner_id=owner.id, org_id=org.id, **provider_fields)
                session.add(provider)
                await session.flush()
                providers_created += 1
                print(
                    f"✅ Created provider '{practice_name}' "
                    f"for {fixture['owner_email']}"
                )

            existing = await session.execute(
                select(Post)
                .join(
                    OpeningDetail,
                    OpeningDetail.post_id == Post.id,
                )
                .where(
                    Post.kind == "opening",
                    Post.owner_id == owner.id,
                    OpeningDetail.provider_id == provider.id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  PA post '{practice_name}' by {fixture['owner_email']} "
                    f"already exists, skipping"
                )
                skipped += 1
                continue

            post = Post(kind="opening", owner_id=owner.id)
            _shift_created_at(post, fixture["days_ago"])
            post.opening_detail = OpeningDetail(
                provider_id=provider.id, **fixture["detail"]
            )
            session.add(post)
            print(f"✅ Created PA post '{practice_name}' by {fixture['owner_email']}")
            created += 1

        await session.commit()

    if providers_created:
        print(f"   ({providers_created} provider profiles created)")
    return created, skipped


async def seed_referral() -> tuple[int, int]:
    """Seed client-referral posts (the seeking side). Idempotent on
    `(kind, owner_id, description)`: descriptions are verbose enough
    that re-running matches the same row, never a collision with a
    real one."""
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_REFERRAL:
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            description = fixture["detail"]["description"]
            short = description[:40] + "…"
            if owner is None:
                print(
                    f"⚠️  CR post '{short}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            existing = await session.execute(
                select(Post)
                .join(ReferralDetail, ReferralDetail.post_id == Post.id)
                .where(
                    Post.kind == "referral",
                    Post.owner_id == owner.id,
                    ReferralDetail.description == description,
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  CR post '{short}' by {fixture['owner_email']} "
                    f"already exists, skipping"
                )
                skipped += 1
                continue

            post = Post(kind="referral", owner_id=owner.id)
            _shift_created_at(post, fixture["days_ago"])
            post.referral_detail = ReferralDetail(**fixture["detail"])
            session.add(post)
            print(f"✅ Created CR post '{short}' by {fixture['owner_email']}")
            created += 1

        await session.commit()

    return created, skipped


class FixtureProgram(TypedDict):
    owner_email: str
    org_name: str
    name: str
    description: str
    state_preference: str | None
    accepting_referrals: bool


# Programs attached to seeded Orgs. ``org_name`` matches an Org created
# by ``seed_opening`` (Org names are the practice's
# display name post-#524). The seed finds-or-creates the Org idempotently
# if PA seeding ran first, then attaches the Program by name.
FIXTURE_PROGRAMS: list[FixtureProgram] = [
    {
        "owner_email": "alice@example.com",
        "org_name": "RISE IOP at CHC",
        "name": "RISE Intensive Outpatient",
        "description": (
            "Comprehensive DBT intensive outpatient program for high school "
            "students with high acuity. Rolling intake; M-F 8:30am-4:30pm."
        ),
        "state_preference": "CA",
        "accepting_referrals": True,
    },
    {
        "owner_email": "alice@example.com",
        "org_name": "RISE IOP at CHC",
        "name": "RISE Summer Cohort",
        "description": (
            "Time-bounded summer cohort of the RISE IOP program, scoped to "
            "rising 11th and 12th graders. Two waves: June and August."
        ),
        "state_preference": "CA",
        "accepting_referrals": True,
    },
]


async def seed_programs() -> tuple[int, int]:
    """Seed Programs attached to already-seeded Orgs. Idempotent on
    ``(org_name, name)``."""
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_PROGRAMS:
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  Program '{fixture['name']}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            org_result = await session.execute(
                select(Organization).where(Organization.name == fixture["org_name"])
            )
            org = org_result.scalar_one_or_none()
            if org is None:
                print(
                    f"⚠️  Program '{fixture['name']}': "
                    f"org '{fixture['org_name']}' not found "
                    "(was provider-availability seeded?), skipping"
                )
                skipped += 1
                continue

            existing = await session.execute(
                select(Program).where(
                    Program.org_id == org.id, Program.name == fixture["name"]
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  Program '{fixture['name']}' at '{fixture['org_name']}' "
                    "already exists, skipping"
                )
                skipped += 1
                continue

            session.add(
                Program(
                    owner_id=owner.id,
                    org_id=org.id,
                    name=fixture["name"],
                    description=fixture["description"],
                    state_preference=fixture["state_preference"],
                    accepting_referrals=fixture["accepting_referrals"],
                )
            )
            print(
                f"✅ Created Program '{fixture['name']}' at " f"'{fixture['org_name']}'"
            )
            created += 1

        await session.commit()

    return created, skipped


class FixtureIntake(TypedDict):
    owner_email: str
    org_name: str
    program_name: str
    days_ago: int
    detail: dict[str, Any]


# Program-availability post fixtures. ``org_name`` + ``program_name``
# match a Program seeded by :func:`seed_programs`; the seed looks them up
# and skips if the Program isn't present. Mirrors PA fixtures'
# idempotency shape.
FIXTURE_PROGRAM_AVAILABILITY: list[FixtureIntake] = [
    {
        "owner_email": "alice@example.com",
        "org_name": "RISE IOP at CHC",
        "program_name": "RISE Intensive Outpatient",
        "days_ago": 2,
        "detail": {
            "description": (
                "RISE IOP currently has openings in the rolling intake. "
                "DBT-based intensive outpatient, M-F 8:30am-4:30pm. "
                "Adolescents and young adults; high-acuity presentations "
                "welcome."
            ),
            "referral_instructions": (
                "Email intake coordinator with the referred client's first "
                "name, age, primary diagnosis, and current level of care."
            ),
            "website": "https://example.com/rise-iop",
            "services": ["psychotherapy", "evaluation"],
            "settings": ["iop"],
            "age_groups": ["adolescents_14_18", "young_adults_19_24"],
            "languages": ["en"],
            "genders": [],
        },
    },
]


async def seed_intake() -> tuple[int, int]:
    """Seed Program-availability posts. Idempotent on
    ``(kind='intake', owner_id, program_id)`` — re-running
    against an existing fixture skips."""
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_PROGRAM_AVAILABILITY:
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  Program-availability post for "
                    f"'{fixture['program_name']}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue

            program_result = await session.execute(
                select(Program)
                .join(Organization, Organization.id == Program.org_id)
                .where(
                    Organization.name == fixture["org_name"],
                    Program.name == fixture["program_name"],
                )
            )
            program = program_result.scalar_one_or_none()
            if program is None:
                print(
                    f"⚠️  Program-availability post for "
                    f"'{fixture['program_name']}': Program not found "
                    "(was programs seeded?), skipping"
                )
                skipped += 1
                continue

            existing = await session.execute(
                select(Post)
                .join(
                    IntakeDetail,
                    IntakeDetail.post_id == Post.id,
                )
                .where(
                    Post.kind == "intake",
                    Post.owner_id == owner.id,
                    IntakeDetail.program_id == program.id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                print(
                    f"⏭️  Program-availability post for "
                    f"'{fixture['program_name']}' already exists, skipping"
                )
                skipped += 1
                continue

            post = Post(kind="intake", owner_id=owner.id)
            _shift_created_at(post, fixture["days_ago"])
            post.intake_detail = IntakeDetail(
                program_id=program.id, **fixture["detail"]
            )
            session.add(post)
            print(
                f"✅ Created Program-availability post for "
                f"'{fixture['program_name']}' by {fixture['owner_email']}"
            )
            created += 1

        await session.commit()

    return created, skipped


# Provider credential fixtures keyed by `(owner_email, org_name)` — that
# pair uniquely identifies a seeded Provider via the find-or-create rule
# in `seed_opening`. Each entry's three lists are inserted as
# `ProviderLicensure` / `ProviderEducation` / `ProviderCertification`
# rows linked back to the Provider. Idempotency: rows are matched on
# `(provider_id, <natural-key>)` so re-running the seed is a no-op.
class FixtureCredentialSet(TypedDict):
    owner_email: str
    org_name: str
    licensures: list[dict[str, Any]]
    educations: list[dict[str, Any]]
    certifications: list[dict[str, Any]]


FIXTURE_CREDENTIALS: list[FixtureCredentialSet] = [
    {
        "owner_email": "alice@example.com",
        "org_name": "Katie Reeves, PhD",
        "licensures": [
            {
                "license_type": "psyd",
                "license_number": "PSY-21089",
                "issuing_state": "CA",
                "expiration_date": "2027-08-31",
            },
        ],
        "educations": [
            {
                "education_type": "phd",
                "institution": "Stanford University",
                "month_completed": "2008-06",
            },
        ],
        "certifications": [
            {
                "certification_type": "emdr",
                "certifying_body": "EMDR International Association",
                "expiration_date": None,
            },
        ],
    },
    {
        "owner_email": "alice@example.com",
        "org_name": "Camp BooHoo",
        "licensures": [
            {
                "license_type": "lcsw",
                "license_number": "LCS-44012",
                "issuing_state": "CA",
                "expiration_date": "2026-12-31",
            },
        ],
        "educations": [
            {
                "education_type": "msw",
                "institution": "University of Southern California",
                "month_completed": "2015-05",
            },
        ],
        "certifications": [],
    },
    {
        "owner_email": "alice@example.com",
        "org_name": "RISE IOP at CHC",
        "licensures": [
            {
                "license_type": "md",
                "license_number": "MD-A-78321",
                "issuing_state": "CA",
                "expiration_date": "2028-03-31",
            },
        ],
        "educations": [
            {
                "education_type": "md",
                "institution": "UC San Francisco School of Medicine",
                "month_completed": "2010-06",
            },
        ],
        "certifications": [
            {
                "certification_type": "dbt",
                "certifying_body": "Linehan Board",
                "expiration_date": None,
            },
        ],
    },
    {
        "owner_email": "dr_chen@example.com",
        "org_name": "Lakeside Therapy Collective",
        # Multi-state licensure — exercises the issuing_state filter on
        # /providers.
        "licensures": [
            {
                "license_type": "lcsw",
                "license_number": "LCS-31118",
                "issuing_state": "CA",
                "expiration_date": "2027-04-30",
            },
            {
                "license_type": "lcsw",
                "license_number": "C28-991",
                "issuing_state": "NV",
                "expiration_date": "2027-06-30",
            },
        ],
        "educations": [
            {
                "education_type": "msw",
                "institution": "UC Berkeley",
                "month_completed": "2012-05",
            },
        ],
        "certifications": [
            {
                "certification_type": "dbt",
                "certifying_body": "Behavioral Tech",
                "expiration_date": "2026-09-30",
            },
            {
                "certification_type": "gottman_1",
                "certifying_body": "The Gottman Institute",
                "expiration_date": None,
            },
        ],
    },
    {
        "owner_email": "dr_patel@example.com",
        "org_name": "Greenfield Psychiatry",
        "licensures": [
            {
                "license_type": "pmhnp",
                "license_number": "NP-55012",
                "issuing_state": "CA",
                "expiration_date": "2027-11-30",
            },
        ],
        "educations": [
            {
                "education_type": "ma_ms",
                "institution": "Johns Hopkins School of Nursing",
                "month_completed": "2018-12",
            },
        ],
        "certifications": [
            {
                "certification_type": "ccatp",
                "certifying_body": "Evergreen Certifications",
                "expiration_date": None,
            },
        ],
    },
    {
        "owner_email": "dr_rivera@example.com",
        "org_name": "Rivera Family Psychology",
        "licensures": [
            {
                "license_type": "lmft",
                "license_number": "MFC-22001",
                "issuing_state": "CA",
                "expiration_date": "2026-08-31",
            },
        ],
        "educations": [
            {
                "education_type": "ma_ms",
                "institution": "Pepperdine University",
                "month_completed": "2016-05",
            },
        ],
        "certifications": [
            {
                "certification_type": "gottman_2",
                "certifying_body": "The Gottman Institute",
                "expiration_date": None,
            },
        ],
    },
    {
        "owner_email": "dr_okafor@example.com",
        "org_name": "Beacon Hill Family Therapy",
        # Multi-state licensure across MA + NY.
        "licensures": [
            {
                "license_type": "lmft",
                "license_number": "LMFT-MA-1099",
                "issuing_state": "MA",
                "expiration_date": "2027-05-31",
            },
            {
                "license_type": "lmft",
                "license_number": "LMFT-NY-22301",
                "issuing_state": "NY",
                "expiration_date": "2027-09-30",
            },
        ],
        "educations": [
            {
                "education_type": "ma_ms",
                "institution": "Boston University",
                "month_completed": "2014-06",
            },
        ],
        "certifications": [
            {
                "certification_type": "gottman_3",
                "certifying_body": "The Gottman Institute",
                "expiration_date": None,
            },
            {
                "certification_type": "cpr",
                "certifying_body": "American Red Cross",
                "expiration_date": "2026-03-31",
            },
        ],
    },
    {
        "owner_email": "dr_jansen@example.com",
        "org_name": "Mountainview Residential",
        "licensures": [
            {
                "license_type": "pmhnp",
                "license_number": "PMHNP-CA-887",
                "issuing_state": "CA",
                "expiration_date": "2028-01-31",
            },
        ],
        "educations": [
            {
                "education_type": "ma_ms",
                "institution": "UCSF School of Nursing",
                "month_completed": "2017-12",
            },
        ],
        "certifications": [
            {
                "certification_type": "ccatp",
                "certifying_body": "Evergreen Certifications",
                "expiration_date": None,
            },
            {
                "certification_type": "dbt",
                "certifying_body": "Behavioral Tech",
                "expiration_date": "2027-02-28",
            },
        ],
    },
    {
        "owner_email": "dr_chen@example.com",
        "org_name": "Cascade PHP",
        "licensures": [
            {
                "license_type": "do",
                "license_number": "DO-OR-4421",
                "issuing_state": "OR",
                "expiration_date": "2027-07-31",
            },
        ],
        "educations": [
            {
                "education_type": "do",
                "institution": "Western University of Health Sciences",
                "month_completed": "2011-06",
            },
        ],
        "certifications": [
            {
                "certification_type": "cpr",
                "certifying_body": "American Heart Association",
                "expiration_date": "2026-06-30",
            },
        ],
    },
    {
        "owner_email": "bob@example.com",
        "org_name": "North Loop Counseling",
        "licensures": [
            {
                "license_type": "lpc",
                "license_number": "LPC-MN-7012",
                "issuing_state": "MN",
                "expiration_date": "2027-03-31",
            },
            {
                "license_type": "lmhc",
                "license_number": "LMHC-WI-2210",
                "issuing_state": "WI",
                "expiration_date": "2026-10-31",
            },
        ],
        "educations": [
            {
                "education_type": "ba_bs",
                "institution": "University of Minnesota",
                "month_completed": "2010-05",
            },
            {
                "education_type": "edd",
                "institution": "Walden University",
                "month_completed": "2020-12",
            },
        ],
        "certifications": [
            {
                "certification_type": "cbt",
                "certifying_body": "Beck Institute",
                "expiration_date": None,
            },
        ],
    },
]


def _parse_date(value: Any) -> date | None:
    """Convert a fixture date (string `"YYYY-MM-DD"` or already-`date` or
    `None`) to the Python `date` SQLite expects on a `Date` column."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


async def seed_credentials() -> tuple[int, int]:
    """Seed Provider credential rows (licensures / education /
    certifications). Idempotent on `(provider_id, license_number)` /
    `(provider_id, institution, month_completed)` /
    `(provider_id, certification_type, certifying_body)`.

    Runs AFTER `seed_opening` since it joins by `(owner_email, org_name)`
    to find the Provider row to attach credentials to. Missing
    Providers are logged and skipped — never the seed's fault, always
    a fixture data issue.
    """
    created = 0
    skipped = 0

    async with async_session_maker() as session:
        for fixture in FIXTURE_CREDENTIALS:
            owner_result = await session.execute(
                select(User).where(User.email == fixture["owner_email"])
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                print(
                    f"⚠️  credentials for '{fixture['org_name']}': "
                    f"owner {fixture['owner_email']} not found, skipping"
                )
                skipped += 1
                continue
            org_result = await session.execute(
                select(Organization).where(Organization.name == fixture["org_name"])
            )
            org = org_result.scalar_one_or_none()
            if org is None:
                print(
                    f"⚠️  credentials for '{fixture['org_name']}': "
                    f"org not found (did seed_opening run?), skipping"
                )
                skipped += 1
                continue
            provider_result = await session.execute(
                select(Provider).where(
                    Provider.owner_id == owner.id,
                    Provider.org_id == org.id,
                )
            )
            provider = provider_result.scalar_one_or_none()
            if provider is None:
                print(
                    f"⚠️  credentials for '{fixture['org_name']}': "
                    f"provider not found, skipping"
                )
                skipped += 1
                continue

            for lic in fixture["licensures"]:
                existing = await session.execute(
                    select(ProviderLicensure).where(
                        ProviderLicensure.provider_id == provider.id,
                        ProviderLicensure.license_number == lic["license_number"],
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    skipped += 1
                    continue
                row_fields = dict(lic)
                row_fields["expiration_date"] = _parse_date(
                    row_fields.get("expiration_date")
                )
                session.add(ProviderLicensure(provider_id=provider.id, **row_fields))
                created += 1
            for edu in fixture["educations"]:
                existing = await session.execute(
                    select(ProviderEducation).where(
                        ProviderEducation.provider_id == provider.id,
                        ProviderEducation.institution == edu["institution"],
                        ProviderEducation.month_completed == edu.get("month_completed"),
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    skipped += 1
                    continue
                session.add(ProviderEducation(provider_id=provider.id, **edu))
                created += 1
            for cert in fixture["certifications"]:
                existing = await session.execute(
                    select(ProviderCertification).where(
                        ProviderCertification.provider_id == provider.id,
                        ProviderCertification.certification_type
                        == cert["certification_type"],
                        ProviderCertification.certifying_body
                        == cert["certifying_body"],
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    skipped += 1
                    continue
                row_fields = dict(cert)
                row_fields["expiration_date"] = _parse_date(
                    row_fields.get("expiration_date")
                )
                session.add(
                    ProviderCertification(provider_id=provider.id, **row_fields)
                )
                created += 1
            print(
                f"✅ Seeded credentials for '{fixture['org_name']}' "
                f"({len(fixture['licensures'])} licensures, "
                f"{len(fixture['educations'])} education, "
                f"{len(fixture['certifications'])} certifications)"
            )
        await session.commit()

    return created, skipped


async def seed_all() -> int:
    users_created, users_skipped = await seed_users()
    # Standalone Orgs (hierarchy roots) before Providers so the latter
    # can attach via `parent_org_name`.
    standalone_orgs_created, standalone_orgs_skipped = await seed_standalone_orgs()
    pa_created, pa_skipped = await seed_opening()
    # Credentials run AFTER seed_opening since they attach to Providers.
    credentials_created, credentials_skipped = await seed_credentials()
    cr_created, cr_skipped = await seed_referral()
    programs_created, programs_skipped = await seed_programs()
    # Program-availability runs AFTER seed_programs() since it joins on a
    # Program seeded above.
    prog_av_created, prog_av_skipped = await seed_intake()

    print(
        f"\n🌱 Seed complete:"
        f" {users_created} users created ({users_skipped} skipped),"
        f" {standalone_orgs_created} standalone orgs created "
        f"({standalone_orgs_skipped} skipped),"
        f" {pa_created} provider-availability posts created ({pa_skipped} skipped),"
        f" {credentials_created} credential rows created "
        f"({credentials_skipped} skipped),"
        f" {cr_created} client-referral posts created ({cr_skipped} skipped),"
        f" {programs_created} programs created ({programs_skipped} skipped),"
        f" {prog_av_created} intake posts created "
        f"({prog_av_skipped} skipped)"
    )
    if users_created > 0:
        print(f"   Password for all fixture users: {SHARED_PASSWORD}")
    return 0


def main() -> int:
    return asyncio.run(seed_all())


if __name__ == "__main__":
    sys.exit(main())
