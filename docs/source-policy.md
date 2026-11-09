# Source and Data Policy

## Purpose

This project demonstrates responsible document intelligence and search over openly reusable official sources.

## Allowed Sources

A source may be ingested only when all of the following are recorded:

1. Official publisher or canonical public-data catalogue.
2. Stable source URL.
3. Document title, authority, language, and publication/version date.
4. Reuse right, licence, or public-domain/official-work basis.
5. Retrieval timestamp and SHA-256 content hash.

## Excluded Content

The project must not ingest, commit, or publicly expose:

- personal data;
- customer, employer, school, or confidential documents;
- credentials, API keys, tokens, or `.env` files;
- full ISO, DIN, IEC, or other copyrighted standards;
- scraped documents without a documented reuse basis.

## Repository Rules

- Raw documents are downloaded locally or stored in Azure Blob Storage only when justified.
- The Git repository stores metadata, hashes, ingestion code, tests, and small non-sensitive fixtures.
- Every public answer must cite its source document and section/page when available.
- The application must show that it is not legal advice.

## Versioning

Each source registry record will include its URL, language, version date, retrieval date, hash, and status. Source changes must result in a new ingestion run and a recorded index version.