# Graduation Project Data Sources

Default enabled sources: GitHub REST API, Hugging Face Hub API, DEV Community API,
Hacker News API, and arXiv API. Legacy hot-list, RSS and GitHub HTML collectors
have been removed, including their registry entries and configuration blocks.
Unknown source codes are rejected during connector construction and data intake.

Repeated collection retains immutable observation snapshots: changed rank,
metrics, descriptions or a new capture day produce a new raw record; identical
same-day observations are reused. Historical references keep their old snapshot.
arXiv publication dates live in metadata, not popularity metrics; historical
timestamp-shaped heat values are also excluded from scoring.

Remote embedding failures fail ingestion and use keyword search for queries.
Local hashing is a separate explicitly identified model used only without remote
configuration. A model/dimension mismatch blocks vector use until a complete
index rebuild. Old vectors marked `unverified:` are excluded from retrieval;
keyword search remains available until the complete index is rebuilt.

## New collectors

- GitHub: https://docs.github.com/en/rest/search/search#search-repositories
  AI-topic repositories pushed within 30 days, sorted by total stars.
  This is not GitHub Trending or a daily star-growth metric.
- Hugging Face: https://huggingface.co/docs/hub/api
  Public model metadata sorted by Hub downloads; no weights or datasets.
- DEV Community: https://developers.forem.com/api
  Programming-tagged articles from the last seven days, including AI development
  and computing practice; no article bodies or user profiles.

arXiv queries include AI, language, learning, vision, distributed computing,
databases, security, operating systems and networking. These are research
updates, not a popularity ranking. Articles are classified by title and then
description; source labels are only a fallback. HN/DEV are not automatically
classified as open source. Topics include AI, computing, open source and products.

Each new collector requests one page (at most 100 records), keeps at most 300
characters of description, and stores only selected metrics, timestamps and
source links. No whole-response storage. HTTP errors end the current fetch;
there is no automatic retry, endpoint rotation or fabricated fallback.
There is no shared cross-worker rate limiter: keep the daily schedule and avoid
repeated manual fetches. Provider quotas and terms must be reviewed before use.

Optional server environment variable: HOTSPOT_GITHUB_TOKEN. Use a minimally
scoped token for public metadata, never put it in frontend config or reports.
Anonymous requests also work subject to GitHub's shared-IP quotas.

Public API availability does not grant unrestricted content redistribution.
Keep source attribution, review provider terms, and separately check rights for
article excerpts or any future full-text processing. Metadata minimization here
applies to the three new collectors, not retroactively to existing records.

## Verification

Run `.venv/Scripts/python.exe scripts/fetch_platform_hotspots.py --limit 3`.
This writes reports only: it does not generate briefings, call an LLM, or push QQ.
The source-health page provides the same three-source manual collection entry.
Custom HOTSPOT_SOURCES_CONFIG files must include the new source codes explicitly.

## Data Lifecycle

Local databases, generated reports, knowledge documents and browser conversations
are runtime data and are not included in the source distribution. Previously
delivered messages and retention by external model services must be managed
separately by the operator.

The repeatable maintenance script is `scripts/purge_legacy_data.py`: preview by
default; `--apply` requires the application server to be stopped first. It resets
generated outputs only when legacy raw records exist, preserving official raw
records and manually imported knowledge documents. Re-generation, not restoration
of the removed content, is the recovery path.
