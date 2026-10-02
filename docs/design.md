# Design

## Purpose

Find relevant job openings from company job boards without checking them by hand, and send only the ones worth reading to Telegram.

## Data flow

```mermaid
flowchart LR
  T[targets.toml] --> F[fetch: greenhouse / lever / ashby /\nworkday / smartrecruiters / workable]
  R[Reed search\nprofile.toml keywords] --> N
  D[DevITjobs RSS + job list] --> N
  F --> N[normalise to Job]
  N --> K[keyword filter\nprofile.toml]
  K --> S[(SQLite\njobs, runs)]
  S -->|new only| L[score with Claude\ncv.md + rubric]
  L --> S
  S -->|score >= threshold| M[Telegram]
```

How a job gets its score, step by step (prompt, reply checks, dealbreaker quotes and cap, retries, cost, when it's sent): [`scoring.md`](scoring.md).

## Job shape (shared by all sources)

| field | type | note |
|---|---|---|
| id | str | `source:company:job_id`, primary key |
| source | str | greenhouse, lever, ashby, workday, smartrecruiters, workable, reed, devitjobs |
| company | str | from targets.toml |
| title | str | |
| location | str | as given by the board |
| url | str | public posting URL |
| description | str | plain text, HTML stripped |
| first_seen | str | ISO timestamp, set on insert |
| score | int or null | null until scored |

## Known limitations

- Only companies using Greenhouse, Lever, Ashby, Workday, SmartRecruiters or Workable are covered.
- Workday has no documented public API; the adapter uses the JSON endpoints Workday's own careers pages call, which can change without notice.
- Workday, SmartRecruiters and Reed list postings without (full) descriptions; details are fetched (one request per posting) only for titles that pass the title filter.
- DevITjobs: the RSS feed has descriptions but no location, the site's job list has locations but no description; they are joined on the job's page slug, and feed items missing from the list are dropped. The list is undocumented: if its shape changes, the source fails with an error rather than passing jobs without locations.
- Reed and DevITjobs results from an employer that is also a target with a readable board are skipped (whole-word name match), so the company's own posting is the one stored. Agency ads and differently named employers can still produce a second copy.
